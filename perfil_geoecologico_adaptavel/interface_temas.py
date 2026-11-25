"""Editor de temas por seleção de camadas. QGIS 3.44, interface desktop."""

# Desenvolvido por João Sipraki
# Copyright (C) 2026 João Sipraki
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,
    QLabel,QPushButton,QScrollArea,QDialogButtonBox,QFileDialog,QMessageBox,QPlainTextEdit,QSpinBox,QComboBox)
from qgis.core import QgsProject,QgsMapLayerProxyModel,QgsCategorizedSymbolRenderer,QgsRasterLayer
from qgis.gui import QgsMapLayerComboBox,QgsFieldComboBox
from processing.gui.wrappers import WidgetWrapper


def decode_rows(value):
    """Aceita valores da matriz do Processing, inclusive ao reabrir parâmetros."""
    if value is None or value == '':return []
    rows=list(value)
    if rows and not isinstance(rows[0],(list,tuple)):
        if len(rows)%4:raise ValueError('A lista de temas precisa de quatro colunas.')
        rows=[rows[i:i+4] for i in range(0,len(rows),4)]
    if any(len(row)!=4 for row in rows):raise ValueError('Linha de temas incompleta.')
    return [['' if v is None else str(v) for v in row] for row in rows if any(v not in ('',None) for v in row)]


def find_layer(project,key):
    if not key:return None
    layer=project.mapLayer(key)
    if layer is not None:return layer
    matches=project.mapLayersByName(key)
    return matches[0] if len(matches)==1 else None


class ThemeRow(QWidget):
    removeRequested=pyqtSignal(object)
    moveRequested=pyqtSignal(object,int)
    def __init__(self,values=None,parent=None):
        super().__init__(parent)
        self.auto_title=''
        layout=QVBoxLayout(self)
        header=QHBoxLayout();self.number=QLabel();header.addWidget(self.number)
        self.title=QLineEdit();self.title.setPlaceholderText('Título da faixa');header.addWidget(self.title,1)
        up=QPushButton('↑');down=QPushButton('↓');remove=QPushButton('Remover')
        up.setToolTip('Mover faixa para cima');down.setToolTip('Mover faixa para baixo')
        up.setFixedWidth(32);down.setFixedWidth(32)
        for button in (up,down,remove):header.addWidget(button)
        up.clicked.connect(lambda:self.moveRequested.emit(self,-1))
        down.clicked.connect(lambda:self.moveRequested.emit(self,1))
        remove.clicked.connect(lambda:self.removeRequested.emit(self))
        layout.addLayout(header)
        line=QHBoxLayout();line.addWidget(QLabel('Camada'))
        self.layer=QgsMapLayerComboBox();self.layer.setFilters(QgsMapLayerProxyModel.PointLayer | QgsMapLayerProxyModel.LineLayer | QgsMapLayerProxyModel.PolygonLayer | QgsMapLayerProxyModel.RasterLayer)
        self.layer.setAllowEmptyLayer(True);self.layer.setLayer(None)
        self.layer.setToolTip('Polígonos formam intervalos; linhas e pontos viram eventos junto ao eixo; rasters são amostrados ao longo do perfil.')
        line.addWidget(self.layer,3);self.field_label=QLabel('Campo');line.addWidget(self.field_label)
        self.field=QgsFieldComboBox();self.field.setAllowEmptyFieldName(True);self.field.setLayer(None)
        line.addWidget(self.field,2)
        self.band=QSpinBox()
        self.band.setMinimum(1)
        self.band.setToolTip('Banda que contém os valores temáticos')
        line.addWidget(self.band)
        layout.addLayout(line)
        self.qml_panel=QWidget();style=QHBoxLayout(self.qml_panel);style.setContentsMargins(0,0,0,0);style.addWidget(QLabel('QML opcional'))
        self.qml=QLineEdit();self.qml.setPlaceholderText('Vazio para usar a simbologia categorizada da camada')
        style.addWidget(self.qml,1);browse=QPushButton('Procurar…');style.addWidget(browse)
        browse.clicked.connect(self.browse);layout.addWidget(self.qml_panel)
        self.raster_panel=QWidget()
        raster_layout=QVBoxLayout(self.raster_panel)
        raster_layout.setContentsMargins(0,0,0,0)
        self.class_mode=QComboBox();self.class_mode.addItems(['Manual','Intervalos iguais','Quantis'])
        self.class_count=QSpinBox();self.class_count.setRange(2,12);self.class_count.setValue(5)
        self.palette=QComboBox()
        self._palette_stops={
            'Viridis':('#440154','#31688e','#35b779','#fde725'),
            'Spectral':('#9e0142','#f46d43','#ffffbf','#66c2a5','#5e4fa2'),
            'RdYlGn':('#d7191c','#fdae61','#ffffbf','#a6d96a','#1a9641'),
            'Risco crescente':('#1a9641','#a6d96a','#ffffbf','#fdae61','#d7191c'),
            'Azuis':('#eff3ff','#9ecae1','#3182bd','#08519c')}
        descriptions={
            'Viridis':'Sequencial e legível; boa escolha geral para valores ordenados.',
            'Spectral':'Contrasta os extremos; use quando valores baixos e altos merecem destaque.',
            'RdYlGn':'Vermelho nos valores baixos e verde nos altos. Evite quando alto significa maior risco.',
            'Risco crescente':'Verde nos valores baixos e vermelho nos altos; use somente se alto significa maior risco.',
            'Azuis':'Escala sequencial azul; útil para magnitude de precipitação quando valores maiores significam mais chuva.'}
        for name,stops in self._palette_stops.items():
            self.palette.addItem(self._palette_icon(stops),name)
            self.palette.setItemData(self.palette.count()-1,descriptions[name],Qt.ToolTipRole)
        self.palette.currentTextChanged.connect(self._update_palette_guidance)
        automatic=QHBoxLayout();automatic.addWidget(QLabel('Classificação'));automatic.addWidget(self.class_mode)
        automatic.addWidget(QLabel('Classes'));automatic.addWidget(self.class_count)
        automatic.addWidget(QLabel('Paleta'));automatic.addWidget(self.palette);raster_layout.addLayout(automatic)
        self.palette_guidance=QLabel();self.palette_guidance.setWordWrap(True)
        raster_layout.addWidget(self.palette_guidance)
        help_label=QLabel('Uma classe por linha. Use mínimo; máximo; rótulo; #RRGGBB')
        raster_layout.addWidget(help_label)
        self.classes=QPlainTextEdit()
        self.classes.setPlaceholderText('0; 3; Plano; #e8edbb\n3; 8; Suave ondulado; #b2cc77')
        self.classes.setMaximumHeight(105)
        raster_layout.addWidget(self.classes)
        layout.addWidget(self.raster_panel)
        self.class_mode.currentIndexChanged.connect(self.raster_mode_changed)
        self.title.textChanged.connect(self._update_palette_guidance)
        self.raster_mode_changed()
        self._update_palette_guidance()
        self.warning=QLabel();self.warning.setWordWrap(True);layout.addWidget(self.warning)
        self.layer.layerChanged.connect(self.layer_changed)
        self.layer_changed(None)
        if values:
            title,key,field,qml=values
            source=find_layer(QgsProject.instance(),key)
            self.layer.setLayer(source)
            self.layer_changed(source)
            self.title.setText(title)
            if field.startswith('banda:'):
                if qml.startswith('@auto|'):
                    parts=qml.split('|')
                    if len(parts)==4:
                        self.class_mode.setCurrentIndex({'equal':1,'quantile':2}.get(parts[1],0))
                        try:self.class_count.setValue(int(parts[2]))
                        except ValueError:pass
                        index=self.palette.findText(parts[3])
                        if index>=0:self.palette.setCurrentIndex(index)
                else:
                    self.class_mode.setCurrentIndex(0)
                    self.classes.setPlainText(qml)
                try:
                    band = int(field.split(':', 1)[1])
                except ValueError:
                    band = 0
                if isinstance(source, QgsRasterLayer) and 1 <= band <= source.bandCount():
                    self.band.setValue(band)
                elif source is not None:
                    self.warning.setText('A banda salva não existe mais. Confirme a banda selecionada.')
            else:
                self.qml.setText(qml)
            if source is not None and not isinstance(source, QgsRasterLayer):
                self.field.setField(field)
                if field not in source.fields().names():
                    self.warning.setText('O campo salvo não existe mais nesta camada. Selecione outro.')
            elif source is None and key:
                self.warning.setText('Camada salva indisponível. Selecione a base novamente; nenhuma substituição foi feita.')
    def layer_changed(self,layer):
        old=self.auto_title
        self.auto_title=layer.name() if layer else ''
        if not self.title.text().strip() or self.title.text()==old:self.title.setText(self.auto_title)
        raster = isinstance(layer, QgsRasterLayer)
        self.field_label.setText('Banda' if raster else 'Campo')
        self.field.setVisible(not raster)
        self.band.setVisible(raster)
        self.qml_panel.setVisible(not raster)
        self.raster_panel.setVisible(raster)
        self.field.setLayer(None if raster else layer)
        self.field.setField('')
        self.warning.setText('')
        if raster:
            self.band.setMaximum(max(1,layer.bandCount()))
            self.band.setValue(1)
        if layer and not raster:
            renderer=layer.renderer()
            if isinstance(renderer,QgsCategorizedSymbolRenderer) and renderer.classAttribute() in layer.fields().names():
                self.field.setField(renderer.classAttribute())
            if layer.customProperty('geo/role',''):
                self.warning.setText('Esta é uma saída de perfil. Escolha a base geográfica original.')
    def raster_mode_changed(self,*args):
        manual=self.class_mode.currentIndex()==0
        self.classes.setVisible(manual)
        self.class_count.setVisible(not manual)
        self.palette.setVisible(not manual)
    @staticmethod
    def _palette_icon(stops):
        pixmap=QPixmap(112,14);pixmap.fill(Qt.transparent)
        gradient=QLinearGradient(0,0,112,0)
        for i,color in enumerate(stops):gradient.setColorAt(i/(len(stops)-1),QColor(color))
        painter=QPainter(pixmap);painter.fillRect(0,1,112,12,gradient)
        painter.setPen(QColor('#667085'));painter.drawRect(0,1,111,11);painter.end()
        return QIcon(pixmap)
    def _update_palette_guidance(self,*args):
        title=self.title.text().casefold()
        description=self.palette.itemData(self.palette.currentIndex(),Qt.ToolTipRole) or ''
        if any(word in title for word in ('precipita','chuva','pluvio')):
            description+=' Se o raster guarda precipitação (mm), Azuis costuma ser mais intuitiva; se guarda um índice de fragilidade, escolha pela direção documentada do índice.'
        elif any(word in title for word in ('fragilidade','risco','vulnerabilidade','suscetibilidade')):
            description+=' Risco crescente só é adequado se valores maiores significam maior fragilidade. O título, sozinho, não determina a semântica.'
        self.palette_guidance.setText(description)
    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,'Escolha o estilo categorizado',self.qml.text(),'Estilo QGIS (*.qml)')
        if path:self.qml.setText(path)
    def values(self):
        layer=self.layer.currentLayer()
        if isinstance(layer, QgsRasterLayer):
            if self.class_mode.currentIndex()==0:
                style=self.classes.toPlainText().strip()
            else:
                method='equal' if self.class_mode.currentIndex()==1 else 'quantile'
                style='@auto|{}|{}|{}'.format(method,self.class_count.value(),self.palette.currentText())
            return [self.title.text().strip(), layer.id(), f'banda:{self.band.value()}', style]
        return [self.title.text().strip(),layer.id() if layer else '',self.field.currentField(),self.qml.text().strip()]


class ThemesDialog(QDialog):
    def __init__(self,values,parent=None):
        super().__init__(parent);self.setWindowTitle('Escolher e ordenar as faixas do perfil');self.resize(960,650)
        self.rows=[];layout=QVBoxLayout(self)
        explanation=QLabel('Adicione uma faixa por tema. Polígonos formam intervalos; linhas e pontos mostram eventos a até 5 m do eixo; rasters usam banda e intervalos de classe. Use ↑ e ↓ para alterar a ordem.');explanation.setWordWrap(True);layout.addWidget(explanation)
        scroll=QScrollArea();scroll.setWidgetResizable(True);container=QWidget();self.row_layout=QVBoxLayout(container);self.row_layout.addStretch();scroll.setWidget(container);layout.addWidget(scroll,1)
        add=QPushButton('Adicionar faixa');add.clicked.connect(lambda:self.add_row());layout.addWidget(add)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        for row in decode_rows(values):self.add_row(row)
        if not self.rows:self.add_row()
    def renumber(self):
        for i,row in enumerate(self.rows,1):row.number.setText('Faixa '+str(i))
    def add_row(self,values=None):
        row=ThemeRow(values,self);row.removeRequested.connect(self.remove_row);row.moveRequested.connect(self.move_row)
        self.rows.append(row);self.row_layout.insertWidget(len(self.rows)-1,row);self.renumber();return row
    def remove_row(self,row):
        self.rows.remove(row);self.row_layout.removeWidget(row);row.setParent(None);row.deleteLater();self.renumber()
    def move_row(self,row,offset):
        i=self.rows.index(row);j=i+offset
        if not 0<=j<len(self.rows):return
        self.rows.pop(i);self.rows.insert(j,row)
        self.row_layout.removeWidget(row);self.row_layout.insertWidget(j,row);self.renumber()
    def values(self):return [cell for row in self.rows for cell in row.values()]
    def accept(self):
        titles=set()
        if not self.rows:
            QMessageBox.warning(self,'Temas','Adicione pelo menos uma faixa.');return
        for i,row in enumerate(self.rows,1):
            title,key,field,qml=row.values();layer=row.layer.currentLayer()
            error=''
            if not title:error='Informe o título.'
            elif len(title)>100 or '\n' in title:error='Use título de até 100 caracteres sem quebra de linha.'
            elif title.casefold() in titles:error='Use títulos diferentes para cada faixa.'
            elif layer is None or not layer.isValid():error='Selecione uma camada válida.'
            elif isinstance(layer, QgsRasterLayer):
                if not qml: error='Informe os intervalos de classificação do raster.'
            elif field not in layer.fields().names():error='Selecione um campo existente.'
            elif layer.customProperty('geo/role',''):error='Selecione a base geográfica original, não uma saída do perfil.'
            elif qml and not Path(qml).is_file():error='O arquivo QML informado não foi encontrado.'
            if error:
                QMessageBox.warning(self,'Faixa '+str(i),error);return
            titles.add(title.casefold())
        super().accept()


class ThemesWidget(QWidget):
    changed=pyqtSignal()
    def __init__(self,parent=None):
        super().__init__(parent);self.setObjectName('geo_themes_widget');self._values=[]
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.summary=QLabel('Nenhuma faixa selecionada');self.summary.setWordWrap(True);layout.addWidget(self.summary,1)
        button=QPushButton('Selecionar faixas…');button.clicked.connect(self.edit);layout.addWidget(button)
    def setValue(self,value):
        rows=decode_rows(value);self._values=[cell for row in rows for cell in row]
        self.summary.setText(' → '.join(row[0] for row in rows) if rows else 'Nenhuma faixa selecionada')
    def value(self):return list(self._values)
    def edit(self):
        dialog=ThemesDialog(self._values,self)
        if dialog.exec():self.setValue(dialog.values());self.changed.emit()


class ThemesWrapper(WidgetWrapper):
    def createWidget(self,**kwargs):
        widget=ThemesWidget();widget.changed.connect(lambda:self.widgetValueHasChanged.emit(self));return widget
    def value(self):return self.widget.value()
    def setValue(self,value):self.widget.setValue(value)
