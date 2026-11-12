import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "agenda-deslocamento-cache-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda


class AgendaDeslocamentoCacheTest(unittest.TestCase):
    def test_reutiliza_lookup_repetido_no_mesmo_par_e_perfil(self) -> None:
        cache = {}
        db = object()

        with patch.object(agenda, "obter_duracao_deslocamento", return_value=(18, "heuristica_haversine")) as mocked:
            first = agenda._obter_duracao_deslocamento_cacheado(
                db,
                origem_clinica_id=10,
                destino_clinica_id=20,
                perfil="Comercial",
                cache=cache,
            )
            second = agenda._obter_duracao_deslocamento_cacheado(
                db,
                origem_clinica_id=10,
                destino_clinica_id=20,
                perfil="comercial",
                cache=cache,
            )

        self.assertEqual(first, (18, "heuristica_haversine"))
        self.assertEqual(second, (18, "heuristica_haversine"))
        self.assertEqual(mocked.call_count, 1)

    def test_fallback_flag_participa_da_chave_do_cache(self) -> None:
        cache = {}
        db = object()

        with patch.object(agenda, "obter_duracao_deslocamento", return_value=(22, "google_routes_api_traffic")) as mocked:
            _ = agenda._obter_duracao_deslocamento_cacheado(
                db,
                origem_clinica_id=1,
                destino_clinica_id=2,
                perfil="comercial",
                permitir_estimativa_fallback=True,
                cache=cache,
            )
            _ = agenda._obter_duracao_deslocamento_cacheado(
                db,
                origem_clinica_id=1,
                destino_clinica_id=2,
                perfil="comercial",
                permitir_estimativa_fallback=False,
                cache=cache,
            )

        self.assertEqual(mocked.call_count, 2)


if __name__ == "__main__":
    unittest.main()
