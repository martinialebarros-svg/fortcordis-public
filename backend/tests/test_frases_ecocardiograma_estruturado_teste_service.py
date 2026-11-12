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


class FrasesEcocardiogramaEstruturadoTesteServiceTest(unittest.TestCase):
    def test_normalize_corrects_context_dependent_pericardial_conclusion(self) -> None:
        payload = service._build_default_store()
        conclusao = next(item for item in payload["aspectos"] if item["key"] == "conclusao")
        conclusao["frases"].append(
            {
                "id": 999,
                "titulo": "Efusao pericardica leve sem tamponamento",
                "texto": (
                    "* Efusão pericárdica discreta (não drenável), sem alterações cardíacas "
                    "estruturais. * Não há critérios ecocardiográficos de tamponamento no momento."
                ),
                "tags": ["efusao_pericardica", "leve"],
                "ativo": 1,
            }
        )

        normalized = service.normalize_external_store(payload)
        conclusao_normalizada = next(
            item for item in normalized["aspectos"] if item["key"] == "conclusao"
        )
        frase = next(item for item in conclusao_normalizada["frases"] if item["id"] == 999)

        self.assertIn("Efusão pericárdica discreta (não drenável).", frase["texto"])
        self.assertNotIn("sem alterações cardíacas estruturais", frase["texto"])
        self.assertIn("Não há critérios ecocardiográficos de tamponamento", frase["texto"])
        self.assertEqual(service.normalize_external_store(normalized), normalized)

    def test_create_phrase_persists_new_phrase_in_aspect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            frases_file = data_dir / "frases_ecocardiograma_estruturado_teste.json"

            original_data_dir = service.DATA_DIR
            original_frases_file = service.FRASES_FILE
            try:
                service.DATA_DIR = data_dir
                service.FRASES_FILE = frases_file

                created = service.create_phrase(
                    {
                        "aspecto": "conclusao",
                        "titulo": "Conclusao com disfuncao diastolica grau 1",
                        "texto": (
                            "Achados compativeis com endocardiose de valva mitral em estagio B1 "
                            "associada a disfuncao diastolica grau 1."
                        ),
                        "tags": ["conclusao", "endocardiose", "b1"],
                    }
                )
                payload = service.get_payload()
                aspecto_conclusao = next(
                    item for item in payload["aspectos"] if item["key"] == "conclusao"
                )

                self.assertIsInstance(created["id"], int)
                self.assertTrue(
                    any(
                        frase["titulo"] == "Conclusao com disfuncao diastolica grau 1"
                        for frase in aspecto_conclusao["frases"]
                    )
                )
            finally:
                service.DATA_DIR = original_data_dir
                service.FRASES_FILE = original_frases_file

    def test_create_phrase_rejects_duplicate_title_in_same_aspect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            frases_file = data_dir / "frases_ecocardiograma_estruturado_teste.json"

            original_data_dir = service.DATA_DIR
            original_frases_file = service.FRASES_FILE
            try:
                service.DATA_DIR = data_dir
                service.FRASES_FILE = frases_file

                payload = service.get_payload()
                primeira_frase = payload["aspectos"][0]["frases"][0]

                with self.assertRaisesRegex(
                    ValueError, "Ja existe uma frase com esse titulo neste aspecto."
                ):
                    service.create_phrase(
                        {
                            "aspecto": payload["aspectos"][0]["key"],
                            "titulo": primeira_frase["titulo"],
                            "texto": "Texto alternativo para validar duplicidade.",
                            "tags": [],
                        }
                    )
            finally:
                service.DATA_DIR = original_data_dir
                service.FRASES_FILE = original_frases_file

    def test_updates_generate_runtime_backups(self) -> None:
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

                service.get_payload()
                service.create_phrase(
                    {
                        "aspecto": "conclusao",
                        "titulo": "Conclusao teste backup",
                        "texto": "Texto de conclusao para validar backup automatico.",
                        "tags": ["backup"],
                    }
                )
                service.update_phrase(
                    1,
                    {
                        "aspecto": "valva_mitral",
                        "titulo": "Aspecto habitual",
                        "texto": "Texto atualizado para validar snapshot de runtime.",
                        "tags": ["atualizado"],
                    },
                )

                backups = sorted(runtime_backup_dir.glob("*.json"))
                self.assertGreaterEqual(len(backups), 2)
            finally:
                service.DATA_DIR = original_data_dir
                service.FRASES_FILE = original_frases_file
                service.RUNTIME_BACKUP_DIR = original_runtime_backup_dir

    def test_preset_changes_generate_runtime_backups(self) -> None:
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

                service.get_payload()
                created = service.save_preset(
                    {
                        "label": "Preset teste runtime",
                        "patologia": "Teste",
                        "grau": "Leve",
                        "descricao": "Preset para validar backup no ciclo de salvar/excluir.",
                        "selecoes": [
                            {
                                "aspecto": "valva_mitral",
                                "frase_titulo": "Aspecto habitual",
                            }
                        ],
                    }
                )
                payload_after_create = service.get_payload()
                self.assertTrue(
                    any(
                        preset["id"] == created["id"]
                        for preset in payload_after_create.get("presets") or []
                    )
                )

                service.delete_preset(int(created["id"]))

                payload_after_delete = service.get_payload()
                deleted = next(
                    preset
                    for preset in payload_after_delete.get("presets") or []
                    if preset["id"] == created["id"]
                )
                self.assertEqual(deleted["ativo"], 0)

                backup_names = [path.name for path in sorted(runtime_backup_dir.glob("*.json"))]
                self.assertTrue(any("__save_preset" in name for name in backup_names))
                self.assertTrue(any("__delete_preset" in name for name in backup_names))
            finally:
                service.DATA_DIR = original_data_dir
                service.FRASES_FILE = original_frases_file
                service.RUNTIME_BACKUP_DIR = original_runtime_backup_dir

    def test_normalize_adds_phrase_pathologies_and_order(self) -> None:
        payload = service.normalize_external_store(
            {
                "version": "1.0",
                "mode": "teste",
                "aspectos": [
                    {
                        "key": "conclusao",
                        "frases": [
                            {
                                "id": 55,
                                "titulo": "Conclusao legado",
                                "texto": "Texto legado sem novos metadados.",
                                "tags": ["normal"],
                                "ativo": 1,
                            }
                        ],
                    }
                ],
                "presets": [],
            }
        )

        conclusao = next(item for item in payload["aspectos"] if item["key"] == "conclusao")
        frase = conclusao["frases"][0]
        self.assertEqual(frase["patologias"], [])
        self.assertEqual(frase["ordem"], 10)

    def test_renaming_phrase_updates_preset_reference_title(self) -> None:
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

                payload = service.get_payload()
                mitral = next(item for item in payload["aspectos"] if item["key"] == "valva_mitral")
                frase = mitral["frases"][0]
                preset = service.save_preset(
                    {
                        "label": "Preset renomear frase",
                        "selecoes": [
                            {
                                "aspecto": "valva_mitral",
                                "frase_id": frase["id"],
                                "frase_titulo": frase["titulo"],
                            }
                        ],
                    }
                )

                service.update_phrase(
                    int(frase["id"]),
                    {
                        "aspecto": "valva_mitral",
                        "titulo": "Mitral normal renomeada",
                        "texto": frase["texto"],
                    },
                )

                updated = service.get_payload()
                preset_updated = next(item for item in updated["presets"] if item["id"] == preset["id"])
                self.assertEqual(preset_updated["selecoes"][0]["frase_titulo"], "Mitral normal renomeada")
            finally:
                service.DATA_DIR = original_data_dir
                service.FRASES_FILE = original_frases_file
                service.RUNTIME_BACKUP_DIR = original_runtime_backup_dir

    def test_moving_phrase_updates_preset_selection_aspect(self) -> None:
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

                payload = service.get_payload()
                mitral = next(item for item in payload["aspectos"] if item["key"] == "valva_mitral")
                frase = mitral["frases"][0]
                preset = service.save_preset(
                    {
                        "label": "Preset mover frase",
                        "selecoes": [
                            {
                                "aspecto": "valva_mitral",
                                "frase_id": frase["id"],
                                "frase_titulo": frase["titulo"],
                            }
                        ],
                    }
                )

                service.update_phrase(
                    int(frase["id"]),
                    {
                        "aspecto": "valva_mitral",
                        "novo_aspecto": "valva_aortica",
                        "titulo": "Frase mitral movida",
                        "texto": frase["texto"],
                    },
                )

                updated = service.get_payload()
                preset_updated = next(item for item in updated["presets"] if item["id"] == preset["id"])
                self.assertEqual(preset_updated["selecoes"][0]["aspecto"], "valva_aortica")
                aortica = next(item for item in updated["aspectos"] if item["key"] == "valva_aortica")
                self.assertTrue(any(item["id"] == frase["id"] for item in aortica["frases"]))
            finally:
                service.DATA_DIR = original_data_dir
                service.FRASES_FILE = original_frases_file
                service.RUNTIME_BACKUP_DIR = original_runtime_backup_dir

    def test_duplicate_and_restore_phrase_and_preset_generate_backups(self) -> None:
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

                payload = service.get_payload()
                mitral = next(item for item in payload["aspectos"] if item["key"] == "valva_mitral")
                frase = mitral["frases"][0]
                cloned_phrase = service.duplicate_phrase(
                    int(frase["id"]),
                    {"aspecto": "valva_mitral", "titulo": "Clone mitral"},
                )
                service.set_phrase_active(int(cloned_phrase["id"]), {"aspecto": "valva_mitral"}, ativo=0)
                restored_phrase = service.set_phrase_active(
                    int(cloned_phrase["id"]), {"aspecto": "valva_mitral"}, ativo=1
                )

                preset = service.save_preset(
                    {
                        "label": "Preset duplicavel",
                        "selecoes": [{"aspecto": "valva_mitral", "frase_id": frase["id"]}],
                    }
                )
                cloned_preset = service.duplicate_preset(int(preset["id"]), {"label": "Clone preset"})
                service.delete_preset(int(cloned_preset["id"]))
                restored_preset = service.restore_preset(int(cloned_preset["id"]))

                self.assertEqual(restored_phrase["ativo"], 1)
                self.assertEqual(restored_preset["ativo"], 1)
                backup_names = [path.name for path in sorted(runtime_backup_dir.glob("*.json"))]
                self.assertTrue(any("__duplicate_phrase" in name for name in backup_names))
                self.assertTrue(any("__restore_phrase" in name for name in backup_names))
                self.assertTrue(any("__duplicate_preset" in name for name in backup_names))
                self.assertTrue(any("__restore_preset" in name for name in backup_names))
            finally:
                service.DATA_DIR = original_data_dir
                service.FRASES_FILE = original_frases_file
                service.RUNTIME_BACKUP_DIR = original_runtime_backup_dir

    def test_corrupted_store_is_recovered_from_runtime_backup(self) -> None:
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

                payload = service.get_payload()
                payload = deepcopy(payload)
                conclusao = next(item for item in payload["aspectos"] if item["key"] == "conclusao")
                conclusao["frases"].append(
                    {
                        "id": 999,
                        "titulo": "Conclusao recuperavel",
                        "texto": "Conteudo que deve voltar apos corrupcao do arquivo.",
                        "tags": ["recovery"],
                        "ativo": 1,
                    }
                )
                service.import_store(payload)
                service._snapshot_current_store("manual_recovery_snapshot")

                frases_file.write_text("{arquivo_corrompido:", encoding="utf-8")

                recovered = service.get_payload()
                recovered_conclusao = next(
                    item for item in recovered["aspectos"] if item["key"] == "conclusao"
                )
                self.assertTrue(
                    any(
                        frase["titulo"] == "Conclusao recuperavel"
                        for frase in recovered_conclusao["frases"]
                    )
                )
            finally:
                service.DATA_DIR = original_data_dir
                service.FRASES_FILE = original_frases_file
                service.RUNTIME_BACKUP_DIR = original_runtime_backup_dir

    def test_minimal_store_is_auto_recovered_from_rich_runtime_backup(self) -> None:
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

                payload = service.get_payload()
                rich_payload = deepcopy(payload)
                base_phrase = rich_payload["aspectos"][0]["frases"][0]
                next_id = max(int(item.get("id") or 0) for item in rich_payload["presets"]) + 1
                for offset in range(6):
                    rich_payload["presets"].append(
                        {
                            "id": next_id + offset,
                            "key": f"preset_extra_{offset}",
                            "label": f"Preset extra {offset}",
                            "patologia": "Teste",
                            "grau": "A",
                            "descricao": "Preset extra para validar autorecovery.",
                            "tags": ["teste"],
                            "ordem": (next_id + offset) * 10,
                            "ativo": 1,
                            "selecoes": [
                                {
                                    "aspecto": rich_payload["aspectos"][0]["key"],
                                    "frase_id": base_phrase["id"],
                                    "frase_titulo": base_phrase["titulo"],
                                }
                            ],
                        }
                    )

                service.import_store(rich_payload)
                service._snapshot_current_store("rich_manual_snapshot")
                service._atomic_write_store(service._build_default_store())

                recovered = service.get_payload()
                labels = {item.get("label") for item in recovered.get("presets") or []}
                self.assertIn("Preset extra 0", labels)
                self.assertGreaterEqual(len(recovered.get("presets") or []), len(rich_payload["presets"]))
            finally:
                service.DATA_DIR = original_data_dir
                service.FRASES_FILE = original_frases_file
                service.RUNTIME_BACKUP_DIR = original_runtime_backup_dir

    def test_save_blocks_unexpected_store_shrink(self) -> None:
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

                payload = service.get_payload()
                rich_payload = deepcopy(payload)
                rich_payload["presets"].append(
                    {
                        "id": 999,
                        "key": "preset_guarda",
                        "label": "Preset guarda",
                        "patologia": "Teste",
                        "grau": "A",
                        "descricao": "Preset para validar bloqueio de shrink.",
                        "tags": ["teste"],
                        "ordem": 9990,
                        "ativo": 1,
                        "selecoes": [
                            {
                                "aspecto": rich_payload["aspectos"][0]["key"],
                                "frase_titulo": rich_payload["aspectos"][0]["frases"][0]["titulo"],
                            }
                        ],
                    }
                )
                service.import_store(rich_payload)

                with self.assertRaisesRegex(ValueError, "perda de dados"):
                    service._save_store(service._build_default_store(), reason="normalize")

                reloaded = service.get_payload()
                self.assertTrue(
                    any(item.get("label") == "Preset guarda" for item in reloaded.get("presets") or [])
                )
            finally:
                service.DATA_DIR = original_data_dir
                service.FRASES_FILE = original_frases_file
                service.RUNTIME_BACKUP_DIR = original_runtime_backup_dir


if __name__ == "__main__":
    unittest.main()
