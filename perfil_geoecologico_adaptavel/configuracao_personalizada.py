"""Validação pura da tabela de temas. Não importa QGIS."""

# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later

import json

def parse_themes(value):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, (list, tuple)):
        raise ValueError('Temas: informe linhas com título, camada, campo e QML opcional.')
    rows = list(value)
    if rows and not isinstance(rows[0], (list, tuple)):
        if len(rows) % 4:
            raise ValueError('A tabela de temas deve ter quatro colunas.')
        rows = [rows[i:i+4] for i in range(0, len(rows), 4)]
    result = []
    for number, row in enumerate(rows, 1):
        if len(row) != 4:
            raise ValueError('Linha {}: são necessárias quatro colunas.'.format(number))
        cells = ['' if v is None else str(v).strip() for v in row]
        if not any(cells):
            continue
        title, layer, field, style = cells
        if not title or not layer or not field:
            raise ValueError('Linha {}: preencha título, camada e campo.'.format(number))
        if len(title) > 100 or '\n' in title:
            raise ValueError('Linha {}: use título de até 100 caracteres, sem quebra de linha.'.format(number))
        if any(t['title'].casefold() == title.casefold() for t in result):
            raise ValueError('Títulos repetidos: ' + title)
        i = len(result) + 1
        result.append(dict(role='TEMA{:03d}'.format(i), title=title, source=layer,
                           field=field, style=style, raster=field.startswith('banda:'), table='faixa_tema_{:03d}'.format(i)))
    if not result:
        raise ValueError('Adicione pelo menos um tema.')
    return result

def layout_signature(themes):
    return json.dumps([(t['role'], t['title']) for t in themes], ensure_ascii=False)
