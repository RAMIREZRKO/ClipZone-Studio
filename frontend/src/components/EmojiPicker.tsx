import { useState } from 'react';

const categories = [
  { name: 'Caras', entries: [
    ['😀', 'Sonrisa', 'feliz grin'], ['😂', 'Risa', 'llorar carcajada lol'], ['🤣', 'Carcajada', 'risa divertido'],
    ['😍', 'Ojos de corazón', 'amor'], ['😎', 'Gafas de sol', 'genial cool'], ['😱', 'Sorpresa', 'grito miedo'],
    ['🤔', 'Pensando', 'duda'], ['🤯', 'Cabeza explosiva', 'sorpresa wow'], ['😭', 'Llanto', 'triste lágrimas'],
  ] },
  { name: 'Gestos', entries: [
    ['👍', 'Pulgar arriba', 'bien like'], ['👏', 'Aplausos', 'bravo clap'], ['🙌', 'Manos arriba', 'celebrar'],
    ['👌', 'Gesto de OK', 'perfecto'], ['✌️', 'Victoria', 'paz peace'], ['👋', 'Saludo', 'hola adiós'],
    ['🫶', 'Manos en corazón', 'amor'], ['👍🏽', 'Pulgar arriba de piel morena', 'like tono'],
    ['🧑🏽‍💻', 'Persona programando', 'tecnología trabajo pc'],
  ] },
  { name: 'Gaming y vídeo', entries: [
    ['🎮', 'Mando de videojuegos', 'gameplay gaming'], ['🎯', 'Diana', 'objetivo target'], ['🏆', 'Trofeo', 'ganar ganador'],
    ['🎥', 'Cámara de vídeo', 'grabar vídeo clip'], ['🎬', 'Claqueta', 'cine clip'], ['🎙️', 'Micrófono', 'audio stream'],
    ['🎧', 'Auriculares', 'audio sonido'], ['🕹️', 'Joystick', 'arcade juego'], ['👾', 'Alien de videojuego', 'retro juego'],
  ] },
  { name: 'Símbolos', entries: [
    ['🔥', 'Fuego', 'llama fire tendencia'], ['❤️', 'Corazón rojo', 'amor love'], ['💚', 'Corazón verde', 'amor'],
    ['✨', 'Destellos', 'brillo estrella'], ['⚡', 'Rayo', 'rápido energía'], ['💥', 'Explosión', 'impacto boom'],
    ['✅', 'Marca de verificación', 'listo bien check'], ['❌', 'Cruz roja', 'error equis'], ['💯', 'Cien puntos', '100 perfecto'],
    ['🚨', 'Sirena', 'alerta urgente'], ['⬇️', 'Flecha abajo', 'descargar'], ['➡️', 'Flecha derecha', 'continuar'],
  ] },
  { name: 'Objetos', entries: [
    ['🎉', 'Confeti', 'fiesta celebrar'], ['🎁', 'Regalo', 'sorteo'], ['🚀', 'Cohete', 'lanzamiento espacio'],
    ['💎', 'Diamante', 'gema brillante'], ['💰', 'Bolsa de dinero', 'premio'], ['🔔', 'Campana', 'aviso notificación'],
    ['📣', 'Megáfono', 'anuncio promoción'], ['⏰', 'Reloj despertador', 'tiempo'], ['🔗', 'Enlace', 'link cadena'],
  ] },
  { name: 'Animales y naturaleza', entries: [
    ['🐶', 'Perro', 'mascota dog'], ['🐱', 'Gato', 'mascota cat'], ['🦊', 'Zorro', 'fox'], ['🦁', 'León', 'felino'],
    ['☀️', 'Sol', 'día verano'], ['🌙', 'Luna', 'noche'], ['🌈', 'Arcoíris', 'colores'], ['🌴', 'Palmera', 'playa vacaciones'],
  ] },
  { name: 'Banderas', entries: [
    ['🇨🇴', 'Colombia', 'bandera'], ['🇲🇽', 'México', 'bandera'], ['🇪🇸', 'España', 'bandera'],
    ['🇦🇷', 'Argentina', 'bandera'], ['🇨🇱', 'Chile', 'bandera'], ['🇵🇪', 'Perú', 'bandera'],
    ['🇪🇨', 'Ecuador', 'bandera'], ['🇺🇸', 'Estados Unidos', 'bandera'],
  ] },
];

const normalize = (text: string) => text.toLowerCase().normalize('NFD').replace(/\p{Diacritic}/gu, '');
function emojiPath(emoji: string) {
  const sequence = emoji.includes('\u200d') ? emoji : emoji.replaceAll('\ufe0f', '');
  const codepoints = Array.from(sequence, char => char.codePointAt(0)!.toString(16)).join('-');
  return import.meta.env.BASE_URL + 'twemoji/17.0.3/' + codepoints + '.svg';
}

function EmojiIcon({ emoji }: { emoji: string }) {
  const [failed, setFailed] = useState(false);
  return failed
    ? <span className="emoji-unicode" aria-hidden="true">{emoji}</span>
    : <img src={emojiPath(emoji)} alt="" width={24} height={24} onError={() => setFailed(true)}/>;
}

export function EmojiPicker({ insert, close }: { insert: (emoji: string) => void; close: () => void }) {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState(0);
  const terms = normalize(query.trim()).split(/\s+/).filter(Boolean);
  const entries = terms.length
    ? categories.flatMap(group => group.entries).filter(([emoji, label, keywords]) =>
      terms.every(term => normalize(`${label} ${keywords}`).includes(term) || emoji.includes(term)))
    : categories[category].entries;

  return <div className="emoji-picker" role="group" aria-label="Selector de emojis"
    onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); close(); } }}>
    <label>Buscar emoji<input type="search" autoFocus value={query} placeholder="Fuego, risa, Colombia…"
      onChange={event => setQuery(event.target.value)}/></label>
    <div className="emoji-categories" role="group" aria-label="Categorías de emojis">
      {categories.map(({ name }, index) => <button type="button" className="secondary" key={name}
        aria-pressed={!terms.length && category === index} onClick={() => { setCategory(index); setQuery(''); }}>{name}</button>)}
    </div>
    <div className="emoji-grid">
      {entries.map(([emoji, label]) => <button type="button" className="secondary" key={emoji} aria-label={label}
        title={label} onClick={() => insert(emoji)}><EmojiIcon emoji={emoji}/></button>)}
      {!entries.length && <span role="status">Sin resultados</span>}
    </div>
    <a href="https://github.com/jdecked/twemoji" target="_blank" rel="noreferrer">Emojis de Twemoji · CC BY 4.0</a>
  </div>;
}
