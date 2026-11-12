# Runbook - OCR de estudos ecocardiograficos

## Dependencias

O importador de imagem e PDF rasterizado usa Tesseract 5 com os idiomas `por` e `eng`.

### Ubuntu/Debian (stage e producao)

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-por tesseract-ocr-eng
```

### macOS

```bash
brew install tesseract tesseract-lang
```

## Configuracao opcional

O caminho padrao e o comando `tesseract` disponivel no `PATH`. Em instalacoes nao padrao:

```bash
export TESSERACT_CMD=/caminho/absoluto/tesseract
export TESSDATA_DIR=/caminho/para/tessdata
```

O backend tambem resolve os caminhos absolutos usuais (`/usr/bin/tesseract`,
`/usr/local/bin/tesseract` e Homebrew) quando a unidade systemd expoe somente
o diretorio do ambiente virtual no `PATH`.

## Verificacao

```bash
tesseract --version
tesseract --list-langs
venv/bin/python scripts/verify_eco_study_ocr.py
```

O ultimo comando deve reconhecer oito medidas tanto na imagem sintetica quanto no PDF rasterizado e terminar com `eco-study OCR smoke: ok`.

O relatorio de `/health`, `/ready` e do diagnostico administrativo inclui `integrations.eco_study_ocr`, com versao, idiomas e eventuais ausencias. A falta do OCR gera alerta operacional, mas nao derruba os outros modulos do FortCordis.

## Liberacao

Antes de habilitar o uso clinico:

1. Aplicar a migracao `20260712_48`.
2. Confirmar o smoke sintetico no mesmo host/processo do backend.
3. Importar amostras anonimizadas dos aparelhos suportados.
4. Comparar todos os valores com um conjunto ouro revisado por veterinario.
5. Manter revisao humana obrigatoria; o importador nao finaliza nem publica laudos.
