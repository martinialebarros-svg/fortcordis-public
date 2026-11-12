import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.services import frases_ecocardiograma_estruturado_teste_service as service


class FrasesEcocardiogramaEstruturadoImportTest(unittest.TestCase):
    def test_import_store_persiste_payload_externo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            frases_file = data_dir / "frases_ecocardiograma_estruturado_teste.json"
            runtime_backup_dir = data_dir / "runtime_backups" / "frases_ecocardiograma_estruturado_teste"

            original_data_dir = service.DATA_DIR
            original_frases_file = service.FRASES_FILE
            original_runtime_backup_dir = service.RUNTIME_BACKUP_DIR
            try:
                service.DATA_DIR = data_dir
                service.FRASES_FILE = frases_file
                service.RUNTIME_BACKUP_DIR = runtime_backup_dir

                payload = service._build_default_store()
                payload["presets"] = [
                    {
                        "id": 1,
                        "key": "preset_personalizado",
                        "label": "Preset personalizado",
                        "patologia": "Teste",
                        "grau": "A",
                        "descricao": "Preset importado de payload externo.",
                        "tags": ["teste"],
                        "ordem": 10,
                        "ativo": 1,
                        "selecoes": [
                            {
                                "aspecto": "valva_mitral",
                                "frase_titulo": payload["aspectos"][0]["frases"][0]["titulo"],
                            }
                        ],
                    }
                ]
                payload["aspectos"] = deepcopy(payload["aspectos"])
                payload["aspectos"][0]["frases"].append(
                    {
                        "titulo": "Frase importada",
                        "texto": "Texto importado para validar persistencia do store.",
                        "tags": ["importada"],
                        "ativo": 1,
                    }
                )

                persisted = service.import_store(payload)
                summary = service.summarize_store(persisted)
                reloaded = service.get_payload()

                self.assertEqual(summary["presets_count"], 1)
                self.assertEqual(reloaded["presets"][0]["label"], "Preset personalizado")
                self.assertTrue(
                    any(
                        frase["titulo"] == "Frase importada"
                        for frase in reloaded["aspectos"][0]["frases"]
                    )
                )
                self.assertTrue(frases_file.exists())

                stored_json = json.loads(frases_file.read_text(encoding="utf-8"))
                self.assertEqual(len(stored_json["presets"]), 1)
            finally:
                service.DATA_DIR = original_data_dir
                service.FRASES_FILE = original_frases_file
                service.RUNTIME_BACKUP_DIR = original_runtime_backup_dir


if __name__ == "__main__":
    unittest.main()
