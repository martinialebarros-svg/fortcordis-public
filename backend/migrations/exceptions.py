"""Excecoes compartilhadas entre o runner e as migracoes versionadas."""
from __future__ import annotations


class MigrationDeferred(RuntimeError):
    """A migracao nao pode ser aplicada agora por uma pendencia de DADOS.

    Diferente de um erro: nao ha nada errado com o codigo nem com o banco. A
    migracao precisa que alguem concilie registros antes de a restricao poder
    existir (por exemplo, duplicidades que violariam um indice unico).

    O runner trata este caso como "adiada": a versao NAO e registrada em
    `schema_migrations`, as migracoes seguintes continuam sendo aplicadas e a
    versao adiada e tentada novamente no proximo deploy. Assim uma pendencia de
    conciliacao deixa de bloquear mudancas de schema que nao tem relacao com
    ela.

    Herda de RuntimeError para nao quebrar quem ja captura RuntimeError.
    """
