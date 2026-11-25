"""Declaração explícita da unidade vertical de MDEs no perfil personalizado."""

# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later

import math


UNIT_CHOICES = ('Não confirmada', 'Metros', 'Pés internacionais', 'Fator personalizado')
FEET_TO_METERS = 0.3048


def resolve_vertical_conversion(choice, custom_factor=1.0):
    """Retorna unidade declarada, escala para metros e estado da confirmação."""
    choice = int(choice)
    if choice == 0:
        return {'unit': UNIT_CHOICES[0], 'factor_to_meters': 1.0, 'confirmed': False}
    if choice == 1:
        return {'unit': UNIT_CHOICES[1], 'factor_to_meters': 1.0, 'confirmed': True}
    if choice == 2:
        return {'unit': UNIT_CHOICES[2], 'factor_to_meters': FEET_TO_METERS, 'confirmed': True}
    if choice == 3:
        try:
            factor = float(custom_factor)
        except (TypeError, ValueError):
            raise ValueError('Informe um fator vertical numérico para converter as cotas em metros.') from None
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError('O fator vertical personalizado precisa ser finito e maior que zero.')
        return {'unit': UNIT_CHOICES[3], 'factor_to_meters': factor, 'confirmed': True}
    raise ValueError('Escolha uma unidade vertical válida para o MDE.')


def layout_vertical_label(info):
    """Texto explícito junto ao gráfico sobre a origem das cotas."""
    if not info.get('confirmed'):
        return 'Altitude: unidade vertical do MDE não confirmada; valores sem conversão'
    unit = info['unit']
    factor = info['factor_to_meters']
    if unit == UNIT_CHOICES[1]:
        return 'Altitude em metros; distância desde A em metros'
    return 'Altitude convertida para metros ({}; fator {:.9g}); distância desde A em metros'.format(
        unit.casefold(), factor)
