
# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later

from qgis.core import QgsProcessingProvider


class PerfilGeoecologicoProvider(QgsProcessingProvider):
    def id(self):
        return 'perfil_geoecologico_adaptavel'

    def name(self):
        return 'Perfil Geoecológico Adaptável'

    def longName(self):
        return self.name()

    def loadAlgorithms(self):
        from .perfil_geoecologico_personalizado import PerfilGeoecologicoPersonalizado
        from .preflight import PreVerificarPerfilGeoecologico
        from .sugestoes import SugerirCamadasPerfil
        self.addAlgorithm(SugerirCamadasPerfil())
        self.addAlgorithm(PreVerificarPerfilGeoecologico())
        self.addAlgorithm(PerfilGeoecologicoPersonalizado())
