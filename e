 README.md                                 |  64 [32m+++++++++[m[31m--[m
 backend/app/ai/__init__.py                |   2 [32m+[m[31m-[m
 backend/app/ai/detector.py                |  90 [32m++++++++++++++++[m
 backend/app/ai/models.py                  |  14 [32m+++[m
 backend/app/ai/routes.py                  |  91 [32m++++++++++++++++[m
 backend/app/ai/whisper_local.py           |  15 [32m+[m[31m--[m
 backend/app/ai/worker.py                  |  57 [32m++++++++++[m
 backend/app/config.py                     |   3 [32m+[m[31m-[m
 backend/app/database.py                   |   7 [32m+[m[31m-[m
 backend/app/main.py                       |  30 [32m++++[m[31m--[m
 backend/app/models.py                     |  56 [32m++++++++[m[31m--[m
 backend/app/services/analysis.py          | 166 [32m++++++++++++++++++++++++++++[m
 backend/pytest.ini                        |   2 [32m+[m
 backend/requirements-ai.lock.txt          |  49 [32m+++++++++[m
 backend/requirements-ai.txt               |   4 [32m+[m[31m-[m
 backend/tests/conftest.py                 |   2 [32m+[m[31m-[m
 backend/tests/test_analysis.py            | 173 [32m++++++++++++++++++++++++++++++[m
 backend/tests/test_detector.py            |  39 [32m+++++++[m
 docs/ARQUITECTURA.md                      |  25 [32m++++[m[31m-[m
 docs/FASES.md                             |  21 [32m++[m[31m--[m
 docs/VALIDACION.md                        |  26 [32m++++[m[31m-[m
 docs/capturas/editor-con-video.png        | Bin [31m274595[m -> [32m310180[m bytes
 docs/capturas/editor-movil.png            | Bin [31m117638[m -> [32m148164[m bytes
 docs/capturas/editor-vacio.png            | Bin [31m211081[m -> [32m246893[m bytes
 docs/capturas/exportaciones.png           | Bin [31m70876[m -> [32m91777[m bytes
 docs/capturas/momentos-ia-movil.png       | Bin [31m0[m -> [32m125297[m bytes
 docs/capturas/momentos-ia.png             | Bin [31m0[m -> [32m127473[m bytes
 frontend/package-lock.json                |   4 [32m+[m[31m-[m
 frontend/package.json                     |   2 [32m+[m[31m-[m
 frontend/src/App.tsx                      |  20 [32m++[m[31m--[m
 frontend/src/api.ts                       |  18 [32m++++[m
 frontend/src/components/AnalysisPanel.tsx | 153 [32m++++++++++++++++++++++++++[m
 frontend/src/presets.ts                   |   1 [32m+[m
 frontend/src/styles.css                   |   4 [32m+[m
 frontend/tests/analysis.spec.ts           |  58 [32m++++++++++[m
 frontend/tests/editor.spec.ts             |   2 [32m+[m
 scripts/create_ai_demo.ps1                |  22 [32m++++[m
 scripts/doctor.py                         |   6 [32m+[m[31m-[m
 scripts/download_model.py                 |  46 [32m++++++++[m
 scripts/setup-ai.ps1                      |  15 [32m+++[m
 40 files changed, 1219 insertions(+), 68 deletions(-)
