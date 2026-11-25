
# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later

def classFactory(iface):
    from .plugin import PerfilGeoecologicoPlugin
    return PerfilGeoecologicoPlugin(iface)
