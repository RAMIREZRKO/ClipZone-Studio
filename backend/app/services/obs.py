"""Cliente de solo lectura del perfil y guardado puntual del búfer de OBS WebSocket 5."""
import base64
import hashlib
import json
from contextlib import contextmanager
from time import monotonic
from uuid import uuid4

from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.sync.client import ClientConnection, connect


class LiveError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code = code
        self.status = status


def auth_response(password: str, salt: str, challenge: str) -> str:
    def digest(value: str) -> str:
        return base64.b64encode(hashlib.sha256(value.encode("utf-8")).digest()).decode("ascii")

    return digest(digest(password + salt) + challenge)


class ObsSession:
    def __init__(self, socket: ClientConnection):
        self.socket = socket

    def send(self, opcode: int, data: dict) -> None:
        self.socket.send(json.dumps({"op": opcode, "d": data}))

    def receive(self, deadline: float) -> tuple[int, dict]:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError
        packet = json.loads(self.socket.recv(timeout=remaining))
        if not isinstance(packet, dict) or not isinstance(packet.get("d"), dict):
            raise ValueError("Mensaje OBS inválido.")
        return packet["op"], packet["d"]

    def identify(self, password: str, outputs: bool) -> None:
        deadline = monotonic() + 3
        opcode, data = self.receive(deadline)
        if opcode != 0 or data.get("rpcVersion", 0) < 1:
            raise LiveError("obs_protocol", "El puerto debe usar OBS WebSocket 5.")
        identify = {"rpcVersion": 1, "eventSubscriptions": 1 << 6 if outputs else 0}
        if auth := data.get("authentication"):
            if not password:
                raise LiveError("obs_auth", "OBS requiere la contraseña de WebSocket. Configura CLIPZONE_OBS_PASSWORD y reinicia ClipZone.")
            identify["authentication"] = auth_response(password, auth["salt"], auth["challenge"])
        self.send(1, identify)
        opcode, data = self.receive(deadline)
        if opcode != 2 or data.get("negotiatedRpcVersion") != 1:
            raise LiveError("obs_protocol", "No se pudo negociar OBS WebSocket 5.")

    def request(self, name: str, fields: dict | None = None) -> dict:
        request_id = uuid4().hex
        deadline = monotonic() + 3
        self.send(6, {"requestType": name, "requestId": request_id, "requestData": fields or {}})
        while True:
            opcode, data = self.receive(deadline)
            if opcode == 7 and data.get("requestId") == request_id:
                return self.response(name, data)

    @staticmethod
    def response(name: str, data: dict) -> dict:
        status = data["requestStatus"]
        if status.get("result") is not True:
            code = status.get("code")
            message = ("OBS rechazó el guardado del búfer" if name == "SaveReplayBuffer" else "OBS rechazó una consulta")
            raise LiveError("obs_request", f"{message} ({code}). Revisa el estado del búfer en OBS.")
        return data.get("responseData") or {}

    def profile(self, category: str, name: str) -> str | None:
        result = self.request("GetProfileParameter", {"parameterCategory": category, "parameterName": name})
        value = result.get("parameterValue")
        return result.get("defaultParameterValue") if value is None else value

    def save(self) -> str:
        request_id = uuid4().hex
        self.send(6, {"requestType": "SaveReplayBuffer", "requestId": request_id})
        acknowledged = False
        path = None
        deadline = monotonic() + 30
        try:
            while not acknowledged or not path:
                opcode, data = self.receive(deadline)
                if opcode == 7 and data.get("requestId") == request_id:
                    self.response("SaveReplayBuffer", data)
                    acknowledged = True
                if opcode == 5 and data.get("eventType") == "ReplayBufferSaved":
                    path = data.get("eventData", {}).get("savedReplayPath")
        except TimeoutError as exc:
            raise LiveError("obs_save_timeout", "OBS no confirmó el archivo a tiempo. Revisa su carpeta de salida antes de volver a capturar.", 504) from exc
        if not isinstance(path, str):
            raise LiveError("obs_file", "OBS devolvió una ruta de repetición inválida.")
        return path


@contextmanager
def obs_session(port: int, password: str, *, outputs: bool = False):
    try:
        with connect(f"ws://127.0.0.1:{port}", subprotocols=["obswebsocket.json"], proxy=None,
                     open_timeout=2, close_timeout=1, max_size=1024 * 1024) as socket:
            session = ObsSession(socket)
            session.identify(password, outputs)
            yield session
    except ConnectionClosed as exc:
        if exc.rcvd and exc.rcvd.code == 4009:
            raise LiveError("obs_auth", "OBS rechazó la contraseña de WebSocket. Verifica CLIPZONE_OBS_PASSWORD.") from exc
        raise LiveError("obs_disconnected", "OBS cerró la conexión. Comprueba que su servidor WebSocket siga activo.", 503) from exc
    except TimeoutError as exc:
        raise LiveError("obs_timeout", "OBS no respondió a tiempo. Comprueba el puerto del servidor WebSocket.", 504) from exc
    except OSError as exc:
        raise LiveError("obs_offline", f"No se pudo conectar con OBS en el puerto local {port}.", 503) from exc
    except (WebSocketException, ValueError, KeyError, TypeError) as exc:
        raise LiveError("obs_protocol", "Respuesta de OBS WebSocket inválida. Verifica que el puerto use OBS WebSocket 5.", 502) from exc
