"""Application settings, with navigation for additional sections."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QListWidget, QSpinBox, QStackedWidget, QVBoxLayout, QDoubleSpinBox, QCheckBox, QMessageBox,
)
from .fusion import default_rrf,validate_rrf,DEFAULT_MINIMUM_SCORE


class SettingsDialog(QDialog):
    settings_applied = Signal(int, int)
    rrf_applied = Signal(object)

    def __init__(self, minimum_score=DEFAULT_MINIMUM_SCORE, uncertainty_threshold=70, parent=None,rrf=None):
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.resize(700, 420)
        self.setMinimumSize(620, 360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)
        body = QHBoxLayout()
        body.setSpacing(16)
        self.sections = QListWidget()
        self.sections.setFixedWidth(145)
        self.sections.setStyleSheet(
            'QListWidget { background: #101722; border: 1px solid #344158; border-radius: 6px; padding: 5px; }'
            'QListWidget::item { padding: 9px; border-radius: 4px; }'
            'QListWidget::item:selected { background: #303d65; color: white; }')
        self.pages = QStackedWidget()
        body.addWidget(self.sections)
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)

        page = QFrame()
        page.setObjectName('panel')
        content = QVBoxLayout(page)
        content.setContentsMargins(18, 18, 18, 18)
        content.setSpacing(14)
        title = QLabel('Auto-link')
        title.setObjectName('panelTitle')
        content.addWidget(title)
        intro = QLabel('Adjust how Suggest links accepts and highlights model suggestions. '
                       'Scores measure similarity; they are not probabilities.')
        intro.setWordWrap(True)
        content.addWidget(intro)
        form = QFormLayout()
        form.setSpacing(12)
        self.minimum_score = self.score_control(minimum_score)
        self.minimum_score.setToolTip('Suggestions below this score stay unlinked. Applies to future Suggest links runs.')
        self.uncertainty_threshold = self.score_control(uncertainty_threshold)
        self.uncertainty_threshold.setToolTip('Linked model suggestions below this score have yellow outlines.')
        form.addRow('Minimum suggestion score', self.minimum_score)
        form.addRow('Uncertainty threshold', self.uncertainty_threshold)
        content.addLayout(form)
        note = QLabel('The minimum affects new suggestions; existing links are kept. '
                      'Changing the uncertainty threshold updates current outline colours and field cards. '
                      'These settings are saved for this computer.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        content.addWidget(note)
        content.addStretch()
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.add_section('Auto-link', page)
        self.add_rrf_section(default_rrf() if rrf is None else validate_rrf(rrf))
        self.sections.setCurrentRow(0)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply |
            QDialogButtonBox.StandardButton.RestoreDefaults)
        self.buttons.accepted.connect(self.save_and_close)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply_values)
        self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.restore_defaults)
        layout.addWidget(self.buttons)

    @staticmethod
    def score_control(value):
        control = QSpinBox()
        control.setRange(0, 100)
        control.setSuffix(' / 100')
        control.setValue(value)
        control.setMinimumWidth(100)
        return control

    def add_section(self, name, page):
        self.sections.addItem(name)
        self.pages.addWidget(page)

    def apply_values(self):
        try:rrf=self.rrf_values()
        except ValueError as error:
            QMessageBox.warning(self,'Invalid RRF settings',str(error));return False
        self.settings_applied.emit(self.minimum_score.value(), self.uncertainty_threshold.value())
        self.rrf_applied.emit(rrf)
        return True

    def save_and_close(self):
        if self.apply_values():self.accept()

    def restore_defaults(self):
        self.minimum_score.setValue(DEFAULT_MINIMUM_SCORE)
        self.uncertainty_threshold.setValue(70)
        self.set_rrf_values(default_rrf())

    def add_rrf_section(self,config):
        page=QFrame();page.setObjectName('panel')
        layout=QVBoxLayout(page);layout.setContentsMargins(18,18,18,18)
        title=QLabel('RRF matching (experimental)');title.setObjectName('panelTitle');layout.addWidget(title)
        warning=QLabel('Only change these values if you understand what you are doing. '
                       'These experimental settings can change which fields are linked.')
        warning.setWordWrap(True);warning.setStyleSheet('color: #fbbf24;');layout.addWidget(warning)
        self.rrf_enabled=QCheckBox('Use weighted reciprocal rank fusion (RRF)')
        layout.addWidget(self.rrf_enabled)
        form=QFormLayout();self.rrf_weights={}
        for name,label in [('bge','BGE Small'),('bge_base','BGE Base'),('granite','Granite'),('mixedbread','Mixedbread')]:
            control=QDoubleSpinBox();control.setRange(0,1000);control.setDecimals(1);control.setSingleStep(1)
            control.setToolTip('Relative weight. All four weights are normalised automatically; zero excludes this model from rank fusion.')
            self.rrf_weights[name]=control;form.addRow(label+' weight',control)
        self.rrf_k=QSpinBox();self.rrf_k.setRange(1,1000)
        self.rrf_k.setToolTip('Rank smoothing constant. Smaller values emphasise top-ranked columns. Tested default: 1.')
        self.rrf_cutoff=self.score_control(50)
        self.rrf_cutoff.setToolTip('Minimum normalised rank score. This is a rank cutoff, not a probability.')
        form.addRow('RRF k',self.rrf_k);form.addRow('Minimum RRF rank score',self.rrf_cutoff)
        layout.addLayout(form)
        self.rrf_shares=QLabel();self.rrf_shares.setWordWrap(True);layout.addWidget(self.rrf_shares)
        note=QLabel('Default relative weights are 9 for Mixedbread and 1 for each other model: 75% and 8.333...% each. The Auto-link minimum suggestion score '
                    'still filters weak evidence before RRF ranking. Field scores and yellow highlighting continue '
                    'to use the average model score. Changes affect future runs; existing links are kept. '
                    'Turn RRF off to use the previous average-score matching.')
        note.setWordWrap(True);note.setObjectName('muted');layout.addWidget(note);layout.addStretch()
        for control in self.rrf_weights.values():control.valueChanged.connect(self.update_rrf_shares)
        self.rrf_enabled.toggled.connect(lambda enabled:[c.setEnabled(enabled) for c in
            [*self.rrf_weights.values(),self.rrf_k,self.rrf_cutoff]])
        self.set_rrf_values(config)
        self.add_section('RRF (experimental)',page)
        self.resize(780,650)

    def update_rrf_shares(self):
        total=sum(c.value() for c in self.rrf_weights.values())
        self.rrf_shares.setText('Normalised shares: '+', '.join(f'{name}: {c.value()/total:.1%}' for name,c in self.rrf_weights.items())
                               if total else 'Set at least one weight above zero.')

    def set_rrf_values(self,config):
        self.rrf_enabled.setChecked(config['enabled'])
        for name,control in self.rrf_weights.items():control.setValue(config['weights'][name]);control.setEnabled(config['enabled'])
        self.rrf_k.setValue(config['k']);self.rrf_cutoff.setValue(round(config['minimum_rank_score']*100))
        self.rrf_k.setEnabled(config['enabled']);self.rrf_cutoff.setEnabled(config['enabled'])
        self.update_rrf_shares()

    def rrf_values(self):
        return validate_rrf(dict(enabled=self.rrf_enabled.isChecked(),k=self.rrf_k.value(),
            minimum_rank_score=self.rrf_cutoff.value()/100,weights={n:c.value() for n,c in self.rrf_weights.items()}))
