import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.agenda_permissions import usuario_pode_excluir_agendamento


class UsuarioFake:
    def __init__(self, papeis):
        self.papeis = {str(papel).strip().lower() for papel in papeis}

    def tem_papel(self, papel):
        return str(papel).strip().lower() in self.papeis


class AgendaDeletePermissionsTests(unittest.TestCase):
    def test_admin_pode_excluir(self):
        self.assertTrue(usuario_pode_excluir_agendamento(UsuarioFake({"admin"})))

    def test_secretaria_pode_excluir(self):
        self.assertTrue(usuario_pode_excluir_agendamento(UsuarioFake({"secretaria"})))

    def test_recepcao_pode_excluir(self):
        self.assertTrue(usuario_pode_excluir_agendamento(UsuarioFake({"recepcao"})))

    def test_aliases_acentuados_podem_excluir(self):
        self.assertTrue(usuario_pode_excluir_agendamento(UsuarioFake({"secretária"})))
        self.assertTrue(usuario_pode_excluir_agendamento(UsuarioFake({"recepção"})))

    def test_multiplos_papeis_nao_dependem_da_ordem(self):
        self.assertTrue(usuario_pode_excluir_agendamento(UsuarioFake({"medico", "recepcao"})))

    def test_outros_papeis_nao_podem_excluir(self):
        self.assertFalse(usuario_pode_excluir_agendamento(UsuarioFake({"medico"})))
        self.assertFalse(usuario_pode_excluir_agendamento(UsuarioFake({"parceiro"})))

    def test_usuario_sem_metodo_de_papel_nao_pode_excluir(self):
        self.assertFalse(usuario_pode_excluir_agendamento(object()))


if __name__ == "__main__":
    unittest.main()
