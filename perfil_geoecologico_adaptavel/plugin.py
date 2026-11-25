
# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later

from qgis.core import QgsApplication
from qgis.PyQt.QtWidgets import QAction

from .provider import PerfilGeoecologicoProvider


class PerfilGeoecologicoPlugin:
    MENU = '&Perfil Geoecológico Adaptável'

    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.action = None
        self.preflight_action = None
        self.suggest_action = None
        self.assistant_action = None

    def initGui(self):
        registry = QgsApplication.processingRegistry()
        if registry.providerById('perfil_geoecologico_adaptavel') is not None:
            raise RuntimeError('O provedor Perfil Geoecológico Adaptável já está carregado.')
        self.provider = PerfilGeoecologicoProvider()
        if not registry.addProvider(self.provider):
            self.provider = None
            raise RuntimeError('O QGIS não conseguiu registrar o provedor de processamento.')

        self.assistant_action = QAction('Assistente guiado…', self.iface.mainWindow())
        self.assistant_action.triggered.connect(self.assistant)
        self.iface.addPluginToMenu(self.MENU, self.assistant_action)

        self.action = QAction('Criar perfil geoecológico…', self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(self.MENU, self.action)
        self.preflight_action = QAction('Pré-verificar entradas…', self.iface.mainWindow())
        self.preflight_action.triggered.connect(self.preflight)
        self.iface.addPluginToMenu(self.MENU, self.preflight_action)
        self.suggest_action = QAction('Sugerir camadas…', self.iface.mainWindow())
        self.suggest_action.triggered.connect(self.suggest)
        self.iface.addPluginToMenu(self.MENU, self.suggest_action)

    def unload(self):
        if self.assistant_action is not None:
            self.iface.removePluginMenu(self.MENU, self.assistant_action)
            self.assistant_action.deleteLater()
            self.assistant_action = None
        if self.action is not None:
            self.iface.removePluginMenu(self.MENU, self.action)
            self.action.deleteLater()
            self.action = None
        if self.preflight_action is not None:
            self.iface.removePluginMenu(self.MENU, self.preflight_action)
            self.preflight_action.deleteLater()
            self.preflight_action = None
        if self.suggest_action is not None:
            self.iface.removePluginMenu(self.MENU, self.suggest_action)
            self.suggest_action.deleteLater()
            self.suggest_action = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def run(self):
        import processing
        processing.execAlgorithmDialog(
            'perfil_geoecologico_adaptavel:perfil_geoecologico_personalizado')

    def assistant(self):
        from .assistente import AssistentePerfilDialog
        dialog = AssistentePerfilDialog(self.iface, self.iface.mainWindow())
        dialog.exec()

    def preflight(self):
        import processing
        processing.execAlgorithmDialog(
            'perfil_geoecologico_adaptavel:preverificar_entradas_perfil')

    def suggest(self):
        import processing
        processing.execAlgorithmDialog(
            'perfil_geoecologico_adaptavel:sugerir_camadas_perfil')
