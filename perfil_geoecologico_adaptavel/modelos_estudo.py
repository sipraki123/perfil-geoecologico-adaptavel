# -*- coding: utf-8 -*-
"""Guias opcionais de composição; nunca definem faixas obrigatórias."""

# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later


STUDY_MODELS = {
    'livre': {
        'titulo': 'Livre — sem modelo',
        'descricao': 'Escolha qualquer combinação de temas. Nenhuma camada é presumida.',
        'papeis': (),
    },
    'paisagem': {
        'titulo': 'Paisagem integrada',
        'descricao': 'Referências comuns: geologia, relevo/geomorfologia, solos, hidrografia, vegetação e uso da terra. Use apenas o que fizer sentido ao estudo.',
        'papeis': ('geologia', 'relevo', 'geomorfologia', 'solos', 'hidrografia/eventos', 'vegetação', 'uso e cobertura da terra', 'clima'),
    },
    'mudanca': {
        'titulo': 'Mudança temporal',
        'descricao': 'Compare temas de datas distintas (por exemplo, uso da terra ou vegetação). Confira ano, método, legenda e comparabilidade; o perfil atual representa uma faixa por tema.',
        'papeis': ('uso e cobertura da terra', 'vegetação', 'clima', 'relevo', 'tema raster'),
    },
    'conservacao': {
        'titulo': 'Conservação / trilha',
        'descricao': 'Considere relevo, drenagem, cobertura/vegetação, solos, geologia e observações de campo. Pontos e eventos podem complementar as faixas.',
        'papeis': ('relevo', 'geomorfologia', 'hidrografia/eventos', 'vegetação', 'solos', 'geologia', 'observações de campo', 'uso e cobertura da terra'),
    },
    'urbano': {
        'titulo': 'Urbano / microclima',
        'descricao': 'Considere cobertura do solo, drenagem, relevo, áreas construídas e observações ambientais. Séries de temperatura/umidade exigem dados temporais comparáveis e não são inferidas automaticamente.',
        'papeis': ('uso e cobertura da terra', 'hidrografia/eventos', 'relevo', 'clima', 'tema raster', 'núcleo urbano', 'observações de campo'),
    },
}


def model_keys():
    return list(STUDY_MODELS)


def model_candidate_match(candidate, model_key):
    """True quando algum papel sugerido coincide com o guia escolhido."""
    roles = set(STUDY_MODELS.get(model_key, {}).get('papeis', ()))
    return bool(roles.intersection(candidate.get('papeis_sugeridos') or ()))


def candidate_visible_for_model(candidate, model_key, filter_enabled):
    """Filtering changes visibility only; it never checks/selects a layer."""
    return (not filter_enabled or model_key == 'livre'
            or model_candidate_match(candidate, model_key))


def model_availability(candidates, model_key):
    """Retorna papéis do guia presentes e ausentes entre as sugestões disponíveis."""
    expected = tuple(STUDY_MODELS.get(model_key, {}).get('papeis', ()))
    present = {role for candidate in candidates for role in (candidate.get('papeis_sugeridos') or ())}
    return ([role for role in expected if role in present],
            [role for role in expected if role not in present])
