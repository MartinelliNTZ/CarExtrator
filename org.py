import os
import sys
import shutil
from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QObject,
    Signal,
    QRunnable,
    QThreadPool,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
    QPoint,
)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QFileDialog,
    QMessageBox,
    QMenu,
    QHeaderView,
    QFrame,
    QLineEdit,
    QGraphicsOpacityEffect,
)


# ==========================================================
# CONFIGURAÇÃO
# ==========================================================

PASTA_MAE_PADRAO = Path(
    r"C:\Users\MatheusMartinelli\OneDrive - Agrorobotica Fotonica Em Certificacoes Agroambientais\VERRA_Farmer"
)

PASTAS_PADRAO = [
    "01_Acessos_Plataforma_IA_AGLIBS",
    "02_Acompanhamento_de_Projeto_Reuniões",
    "03_ENVIO_DE_DOCUMENTOS",
    "04_ATIVIDADES_ATRIBUIDAS",
    "05_ASA",
    "06_CAR",
    "07_MATRICULA",
    "08_LIMITES",
    "09_HISTORICO_COBERTURA_SOLO",
    "10_VERRA",
    "11_AGROROBOTICA",
    "12_FOTOS_INICIO_PROJETO",
]


# ==========================================================
# CORES
# ==========================================================

COR_FUNDO = "#111111"
COR_PAINEL = "#181818"
COR_PAINEL_2 = "#202020"
COR_BORDA = "#333333"

COR_DOURADO = "#D4AF37"
COR_DOURADO_CLARO = "#F1D675"

COR_TEXTO = "#EEEEEE"
COR_TEXTO_SECUNDARIO = "#A9A9A9"

COR_OK = "#61C975"
COR_ERRO = "#E85D5D"
COR_AVISO = "#E6A23C"


# ==========================================================
# AUXILIARES
# ==========================================================

def formatar_tamanho(bytes_total):
    unidades = ["B", "KB", "MB", "GB", "TB"]

    tamanho = float(bytes_total)

    for unidade in unidades:
        if tamanho < 1024:
            if unidade in ("GB", "TB"):
                return f"{tamanho:.2f} {unidade}"

            return f"{tamanho:.1f} {unidade}"

        tamanho /= 1024

    return f"{tamanho:.2f} PB"


def obter_estatisticas_pasta(caminho):
    arquivos = 0
    subpastas = 0
    tamanho = 0

    try:
        for raiz, dirs, files in os.walk(caminho):
            subpastas += len(dirs)
            arquivos += len(files)

            for nome in files:
                arquivo = Path(raiz) / nome

                try:
                    tamanho += arquivo.stat().st_size
                except (PermissionError, FileNotFoundError, OSError):
                    pass

    except (PermissionError, FileNotFoundError, OSError):
        pass

    return arquivos, subpastas, tamanho


def abrir_explorer(caminho):
    try:
        caminho = Path(caminho)

        if sys.platform.startswith("win"):
            os.startfile(str(caminho))

        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(caminho)])

        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(caminho)])

    except Exception as erro:
        QMessageBox.critical(
            None,
            "Erro",
            f"Não foi possível abrir a pasta:\n\n{erro}",
        )


# ==========================================================
# TOAST
# ==========================================================

class Toast(QFrame):

    def __init__(
        self,
        parent,
        mensagem,
        tipo="sucesso",
        duracao=2500,
    ):
        super().__init__(parent)

        self.duracao = duracao

        self.setAttribute(
            Qt.WA_TransparentForMouseEvents
        )

        self.setObjectName("toast")

        cores = {
            "sucesso": ("#163D21", "#61C975"),
            "erro": ("#451D1D", "#E85D5D"),
            "aviso": ("#493A17", "#E6A23C"),
            "info": ("#1A3348", "#5EA8E5"),
        }

        fundo, borda = cores.get(
            tipo,
            cores["sucesso"]
        )

        self.setStyleSheet(
            f"""
            QFrame#toast {{
                background-color: {fundo};
                border: 1px solid {borda};
                border-radius: 8px;
            }}

            QLabel {{
                background: transparent;
                color: #FFFFFF;
                font-size: 10pt;
                padding: 3px;
            }}
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)

        icones = {
            "sucesso": "✓",
            "erro": "✕",
            "aviso": "!",
            "info": "i",
        }

        lbl_icone = QLabel(
            icones.get(tipo, "✓")
        )

        lbl_icone.setStyleSheet(
            f"""
            color: {borda};
            font-size: 14pt;
            font-weight: bold;
            """
        )

        lbl_texto = QLabel(mensagem)

        layout.addWidget(lbl_icone)
        layout.addWidget(lbl_texto)

        self.adjustSize()

        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)

        self.opacity_effect.setOpacity(0)

        self.animacao_entrada = QPropertyAnimation(
            self.opacity_effect,
            b"opacity",
            self,
        )

        self.animacao_entrada.setDuration(180)
        self.animacao_entrada.setStartValue(0)
        self.animacao_entrada.setEndValue(1)

        self.animacao_saida = QPropertyAnimation(
            self.opacity_effect,
            b"opacity",
            self,
        )

        self.animacao_saida.setDuration(300)
        self.animacao_saida.setStartValue(1)
        self.animacao_saida.setEndValue(0)

        self.animacao_saida.finished.connect(
            self.deleteLater
        )

    def mostrar(self):
        parent = self.parentWidget()

        margem = 20

        x = (
            parent.width()
            - self.width()
            - margem
        )

        y = (
            parent.height()
            - self.height()
            - margem
        )

        self.move(x, y)

        self.raise_()
        self.show()

        self.animacao_entrada.start()

        QTimer.singleShot(
            self.duracao,
            self.fechar,
        )

    def fechar(self):
        self.animacao_saida.start()


# ==========================================================
# WORKER
# ==========================================================

class WorkerSignals(QObject):
    finalizado = Signal(
        object,
        str,
        int,
        int,
        int,
    )


class EstatisticasWorker(QRunnable):

    def __init__(
        self,
        item,
        caminho,
    ):
        super().__init__()

        self.item = item
        self.caminho = Path(caminho)

        self.signals = WorkerSignals()

    def run(self):
        arquivos, subpastas, tamanho = (
            obter_estatisticas_pasta(
                self.caminho
            )
        )

        self.signals.finalizado.emit(
            self.item,
            str(self.caminho),
            arquivos,
            subpastas,
            tamanho,
        )


# ==========================================================
# JANELA PRINCIPAL
# ==========================================================

class GerenciadorPastas(QMainWindow):

    def __init__(self):
        super().__init__()

        self.pasta_mae = PASTA_MAE_PADRAO

        self.thread_pool = (
            QThreadPool.globalInstance()
        )

        self.setWindowTitle(
            "AGROROBÓTICA | Gerenciador VERRA Farmer"
        )

        self.resize(
            1500,
            900,
        )

        self.setMinimumSize(
            1100,
            650,
        )

        self.criar_interface()
        self.aplicar_estilo()

        self.carregar_projetos(
            exibir_toast=False
        )

    # ======================================================
    # INTERFACE
    # ======================================================

    def criar_interface(self):

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        layout.setContentsMargins(
            20,
            20,
            20,
            20,
        )

        layout.setSpacing(15)

        # Cabeçalho

        header = QFrame()
        header.setObjectName("header")

        header_layout = QVBoxLayout(header)

        titulo = QLabel(
            "GERENCIADOR DE ESTRUTURA DE PROJETOS"
        )
        titulo.setObjectName("titulo")

        subtitulo = QLabel(
            "VERRA Farmer • Conferência e padronização de diretórios"
        )
        subtitulo.setObjectName("subtitulo")

        header_layout.addWidget(titulo)
        header_layout.addWidget(subtitulo)

        layout.addWidget(header)

        # Barra pasta

        barra = QHBoxLayout()

        barra.addWidget(
            QLabel("Pasta mãe:")
        )

        self.input_pasta = QLineEdit(
            str(self.pasta_mae)
        )

        self.input_pasta.setReadOnly(True)

        barra.addWidget(
            self.input_pasta,
            1,
        )

        btn_escolher = QPushButton(
            "Selecionar pasta"
        )

        btn_escolher.clicked.connect(
            self.selecionar_pasta_mae
        )

        barra.addWidget(
            btn_escolher
        )

        self.btn_atualizar = QPushButton(
            "↻ Atualizar"
        )

        self.btn_atualizar.setObjectName(
            "btnPrincipal"
        )

        self.btn_atualizar.clicked.connect(
            lambda:
            self.carregar_projetos(
                exibir_toast=True
            )
        )

        barra.addWidget(
            self.btn_atualizar
        )

        layout.addLayout(barra)

        # Cards

        resumo = QHBoxLayout()

        self.lbl_projetos = self.criar_card(
            "Projetos",
            "0",
        )

        self.lbl_corretas = self.criar_card(
            "Pastas corretas",
            "0",
        )

        self.lbl_incorretas = self.criar_card(
            "Incoerentes",
            "0",
        )

        self.lbl_ausentes = self.criar_card(
            "Ausentes",
            "0",
        )

        for card in (
            self.lbl_projetos,
            self.lbl_corretas,
            self.lbl_incorretas,
            self.lbl_ausentes,
        ):
            resumo.addWidget(
                card["frame"]
            )

        layout.addLayout(resumo)

        # Pesquisa

        pesquisa_layout = QHBoxLayout()

        pesquisa_layout.addWidget(
            QLabel("Pesquisar projeto:")
        )

        self.input_pesquisa = QLineEdit()

        self.input_pesquisa.setPlaceholderText(
            "Digite parte do nome..."
        )

        self.input_pesquisa.textChanged.connect(
            self.filtrar_projetos
        )

        pesquisa_layout.addWidget(
            self.input_pesquisa,
            1,
        )

        layout.addLayout(
            pesquisa_layout
        )

        # Tree

        self.tree = QTreeWidget()

        self.tree.setColumnCount(6)

        self.tree.setHeaderLabels(
            [
                "Projeto / Pasta",
                "Status",
                "Arquivos",
                "Subpastas",
                "Tamanho",
                "Ações",
            ]
        )

        self.tree.setAnimated(True)
        self.tree.setIndentation(24)

        header = self.tree.header()

        header.setSectionResizeMode(
            0,
            QHeaderView.Stretch,
        )

        for coluna in (1, 2, 3, 4):
            header.setSectionResizeMode(
                coluna,
                QHeaderView.ResizeToContents,
            )

        header.setSectionResizeMode(
            5,
            QHeaderView.Fixed,
        )

        self.tree.setColumnWidth(
            5,
            310,
        )

        self.tree.itemDoubleClicked.connect(
            self.duplo_clique_item
        )

        layout.addWidget(
            self.tree,
            1,
        )

        legenda = QLabel(
            "● Verde = correto    "
            "● Vermelho = incoerente    "
            "● Laranja = ausente"
        )

        legenda.setObjectName(
            "legenda"
        )

        layout.addWidget(
            legenda
        )

    # ======================================================
    # TOAST
    # ======================================================

    def mostrar_toast(
        self,
        mensagem,
        tipo="sucesso",
    ):
        toast = Toast(
            self.centralWidget(),
            mensagem,
            tipo,
        )

        toast.mostrar()

    # ======================================================
    # CARD
    # ======================================================

    def criar_card(
        self,
        titulo,
        valor,
    ):
        frame = QFrame()
        frame.setObjectName("card")

        layout = QVBoxLayout(frame)

        titulo_label = QLabel(titulo)
        titulo_label.setObjectName(
            "cardTitulo"
        )

        valor_label = QLabel(valor)
        valor_label.setObjectName(
            "cardValor"
        )

        layout.addWidget(
            titulo_label
        )

        layout.addWidget(
            valor_label
        )

        return {
            "frame": frame,
            "valor": valor_label,
        }

    # ======================================================
    # SALVAR ESTADO DA ÁRVORE
    # ======================================================

    def salvar_estado_tree(self):

        expandidos = set()

        selecionado = None

        scroll_vertical = (
            self.tree.verticalScrollBar().value()
        )

        for i in range(
            self.tree.topLevelItemCount()
        ):
            item = self.tree.topLevelItem(i)

            caminho = item.data(
                0,
                Qt.UserRole,
            )

            if (
                caminho
                and item.isExpanded()
            ):
                expandidos.add(
                    caminho
                )

        atual = self.tree.currentItem()

        if atual:
            selecionado = atual.data(
                0,
                Qt.UserRole
            )

        return {
            "expandidos": expandidos,
            "selecionado": selecionado,
            "scroll": scroll_vertical,
        }

    def restaurar_estado_tree(
        self,
        estado,
    ):

        selecionado = estado.get(
            "selecionado"
        )

        expandidos = estado.get(
            "expandidos",
            set(),
        )

        for i in range(
            self.tree.topLevelItemCount()
        ):

            projeto_item = (
                self.tree.topLevelItem(i)
            )

            caminho = projeto_item.data(
                0,
                Qt.UserRole,
            )

            if caminho in expandidos:
                projeto_item.setExpanded(
                    True
                )

            if caminho == selecionado:
                self.tree.setCurrentItem(
                    projeto_item
                )

            for j in range(
                projeto_item.childCount()
            ):

                child = projeto_item.child(j)

                caminho_child = child.data(
                    0,
                    Qt.UserRole,
                )

                if caminho_child == selecionado:
                    self.tree.setCurrentItem(
                        child
                    )

        QTimer.singleShot(
            0,
            lambda:
            self.tree.verticalScrollBar().setValue(
                estado.get(
                    "scroll",
                    0,
                )
            ),
        )

    # ======================================================
    # CARREGAMENTO GERAL
    # ======================================================

    def carregar_projetos(
        self,
        exibir_toast=True,
    ):

        caminho = Path(
            self.input_pasta.text()
        )

        if not caminho.exists():

            self.mostrar_toast(
                "Pasta mãe não encontrada.",
                "erro",
            )

            return

        self.pasta_mae = caminho

        # SALVA ESTADO
        estado = self.salvar_estado_tree()

        self.tree.setUpdatesEnabled(False)

        self.tree.clear()

        projetos = sorted(
            [
                p
                for p in self.pasta_mae.iterdir()
                if p.is_dir()
            ],
            key=lambda p: p.name.lower(),
        )

        total_corretas = 0
        total_incorretas = 0
        total_ausentes = 0

        for projeto in projetos:

            projeto_item = (
                self.criar_item_projeto(
                    projeto
                )
            )

            (
                corretas,
                incoerentes,
                ausentes,
            ) = self.carregar_pastas_projeto(
                projeto_item,
                projeto,
            )

            total_corretas += corretas
            total_incorretas += incoerentes
            total_ausentes += ausentes

            self.carregar_estatisticas(
                projeto_item,
                projeto,
            )

        self.tree.setUpdatesEnabled(True)

        self.lbl_projetos["valor"].setText(
            str(len(projetos))
        )

        self.lbl_corretas["valor"].setText(
            str(total_corretas)
        )

        self.lbl_incorretas["valor"].setText(
            str(total_incorretas)
        )

        self.lbl_ausentes["valor"].setText(
            str(total_ausentes)
        )

        self.restaurar_estado_tree(
            estado
        )

        if exibir_toast:

            self.mostrar_toast(
                "Estrutura atualizada com sucesso.",
                "sucesso",
            )

    # ======================================================
    # PROJETO
    # ======================================================

    def criar_item_projeto(
        self,
        projeto,
    ):

        item = QTreeWidgetItem(
            self.tree
        )

        item.setText(
            0,
            projeto.name,
        )

        item.setText(
            1,
            "PROJETO",
        )

        item.setText(2, "...")
        item.setText(3, "...")
        item.setText(4, "...")

        item.setData(
            0,
            Qt.UserRole,
            str(projeto),
        )

        item.setData(
            0,
            Qt.UserRole + 1,
            "projeto",
        )

        fonte = QFont()
        fonte.setBold(True)

        item.setFont(
            0,
            fonte,
        )

        item.setForeground(
            0,
            QColor(COR_DOURADO_CLARO),
        )

        item.setForeground(
            1,
            QColor(COR_DOURADO),
        )

        widget = QWidget()

        layout = QHBoxLayout(widget)

        layout.setContentsMargins(
            2,
            2,
            2,
            2,
        )

        btn_abrir = QPushButton(
            "Abrir"
        )

        btn_abrir.clicked.connect(
            lambda checked=False, p=projeto:
            abrir_explorer(p)
        )

        btn_add = QToolButton()

        btn_add.setText(
            "+ Adicionar pasta"
        )

        btn_add.setPopupMode(
            QToolButton.InstantPopup
        )

        btn_add.setMenu(
            self.criar_menu_adicionar(
                projeto,
                item,
            )
        )

        layout.addWidget(
            btn_abrir
        )

        layout.addWidget(
            btn_add
        )

        self.tree.setItemWidget(
            item,
            5,
            widget,
        )

        return item

    # ======================================================
    # PASTAS PROJETO
    # ======================================================

    def carregar_pastas_projeto(
        self,
        projeto_item,
        projeto,
    ):

        try:
            pastas = sorted(
                [
                    p
                    for p in projeto.iterdir()
                    if p.is_dir()
                ],
                key=lambda p: p.name.lower(),
            )

        except Exception:
            pastas = []

        nomes = {
            p.name
            for p in pastas
        }

        corretas = 0
        incoerentes = 0

        for pasta in pastas:

            if pasta.name in PASTAS_PADRAO:

                status = "CORRETA"
                cor = COR_OK
                corretas += 1

            else:

                status = "INCOERENTE"
                cor = COR_ERRO
                incoerentes += 1

            item = QTreeWidgetItem(
                projeto_item
            )

            item.setText(
                0,
                pasta.name,
            )

            item.setText(
                1,
                status,
            )

            item.setText(2, "...")
            item.setText(3, "...")
            item.setText(4, "...")

            item.setForeground(
                0,
                QColor(cor),
            )

            item.setForeground(
                1,
                QColor(cor),
            )

            item.setData(
                0,
                Qt.UserRole,
                str(pasta),
            )

            item.setData(
                0,
                Qt.UserRole + 1,
                "pasta",
            )

            self.adicionar_acoes_pasta(
                item,
                pasta,
                projeto_item,
            )

            self.carregar_estatisticas(
                item,
                pasta,
            )

        faltantes = [
            nome
            for nome in PASTAS_PADRAO
            if nome not in nomes
        ]

        for nome in faltantes:

            item = QTreeWidgetItem(
                projeto_item
            )

            item.setText(
                0,
                nome,
            )

            item.setText(
                1,
                "AUSENTE",
            )

            item.setText(2, "—")
            item.setText(3, "—")
            item.setText(4, "—")

            item.setForeground(
                0,
                QColor(COR_AVISO),
            )

            item.setForeground(
                1,
                QColor(COR_AVISO),
            )

            item.setData(
                0,
                Qt.UserRole + 1,
                "ausente",
            )

            btn = QPushButton(
                "+ Criar"
            )

            btn.clicked.connect(
                lambda checked=False,
                projeto=projeto,
                nome=nome,
                projeto_item=projeto_item:
                self.criar_pasta(
                    projeto,
                    nome,
                    projeto_item,
                )
            )

            self.tree.setItemWidget(
                item,
                5,
                btn,
            )

        return (
            corretas,
            incoerentes,
            len(faltantes),
        )

    # ======================================================
    # ATUALIZA SOMENTE UM PROJETO
    # ======================================================

    def atualizar_projeto_item(
        self,
        projeto_item,
        projeto,
    ):

        estava_expandido = (
            projeto_item.isExpanded()
        )

        item_selecionado = (
            self.tree.currentItem()
        )

        caminho_selecionado = None

        if item_selecionado:
            caminho_selecionado = (
                item_selecionado.data(
                    0,
                    Qt.UserRole,
                )
            )

        scroll = (
            self.tree.verticalScrollBar().value()
        )

        # limpa filhos
        while projeto_item.childCount():
            projeto_item.takeChild(0)

        self.carregar_pastas_projeto(
            projeto_item,
            projeto,
        )

        projeto_item.setExpanded(
            estava_expandido
        )

        # atualiza estatística projeto
        projeto_item.setText(
            2,
            "..."
        )
        projeto_item.setText(
            3,
            "..."
        )
        projeto_item.setText(
            4,
            "..."
        )

        self.carregar_estatisticas(
            projeto_item,
            projeto,
        )

        # tenta restaurar seleção
        if caminho_selecionado:

            for i in range(
                projeto_item.childCount()
            ):

                child = projeto_item.child(i)

                if (
                    child.data(
                        0,
                        Qt.UserRole,
                    )
                    == caminho_selecionado
                ):
                    self.tree.setCurrentItem(
                        child
                    )
                    break

        QTimer.singleShot(
            0,
            lambda:
            self.tree.verticalScrollBar().setValue(
                scroll
            ),
        )

        self.atualizar_cards()

    # ======================================================
    # CARDS
    # ======================================================

    def atualizar_cards(self):

        projetos = (
            self.tree.topLevelItemCount()
        )

        corretas = 0
        incoerentes = 0
        ausentes = 0

        for i in range(projetos):

            projeto = (
                self.tree.topLevelItem(i)
            )

            for j in range(
                projeto.childCount()
            ):

                status = projeto.child(j).text(
                    1
                )

                if status == "CORRETA":
                    corretas += 1

                elif status == "INCOERENTE":
                    incoerentes += 1

                elif status == "AUSENTE":
                    ausentes += 1

        self.lbl_projetos["valor"].setText(
            str(projetos)
        )

        self.lbl_corretas["valor"].setText(
            str(corretas)
        )

        self.lbl_incorretas["valor"].setText(
            str(incoerentes)
        )

        self.lbl_ausentes["valor"].setText(
            str(ausentes)
        )

    # ======================================================
    # AÇÕES
    # ======================================================

    def adicionar_acoes_pasta(
        self,
        item,
        pasta,
        projeto_item,
    ):

        widget = QWidget()

        layout = QHBoxLayout(widget)

        layout.setContentsMargins(
            2,
            2,
            2,
            2,
        )

        btn_abrir = QPushButton(
            "Abrir"
        )

        btn_abrir.clicked.connect(
            lambda checked=False, p=pasta:
            abrir_explorer(p)
        )

        btn_padronizar = QToolButton()

        btn_padronizar.setText(
            "Padronizar ▼"
        )

        btn_padronizar.setPopupMode(
            QToolButton.InstantPopup
        )

        menu = QMenu(
            btn_padronizar
        )

        for nome in PASTAS_PADRAO:

            action = menu.addAction(
                nome
            )

            action.triggered.connect(
                lambda checked=False,
                origem=pasta,
                destino=nome,
                tree_item=item,
                projeto_item=projeto_item:
                self.renomear_pasta(
                    origem,
                    destino,
                    tree_item,
                    projeto_item,
                )
            )

        btn_padronizar.setMenu(
            menu
        )

        layout.addWidget(
            btn_abrir
        )

        layout.addWidget(
            btn_padronizar
        )

        self.tree.setItemWidget(
            item,
            5,
            widget,
        )

    # ======================================================
    # MENU ADICIONAR
    # ======================================================

    def criar_menu_adicionar(
        self,
        projeto,
        projeto_item,
    ):

        menu = QMenu(self)

        for nome in PASTAS_PADRAO:

            action = menu.addAction(
                nome
            )

            action.triggered.connect(
                lambda checked=False,
                projeto=projeto,
                nome=nome,
                projeto_item=projeto_item:
                self.criar_pasta(
                    projeto,
                    nome,
                    projeto_item,
                )
            )

        return menu

    # ======================================================
    # CRIAR PASTA
    # ======================================================

    def criar_pasta(
        self,
        projeto,
        nome,
        projeto_item,
    ):

        destino = (
            Path(projeto)
            / nome
        )

        if destino.exists():

            self.mostrar_toast(
                f"{nome} já existe.",
                "aviso",
            )

            return

        try:
            destino.mkdir()

            self.atualizar_projeto_item(
                projeto_item,
                Path(projeto),
            )

            self.mostrar_toast(
                f"Pasta criada: {nome}",
                "sucesso",
            )

        except Exception as erro:

            self.mostrar_toast(
                f"Erro ao criar pasta: {erro}",
                "erro",
            )

    # ======================================================
    # RENOMEAR
    # ======================================================

    def renomear_pasta(
        self,
        origem,
        novo_nome,
        tree_item,
        projeto_item,
    ):

        origem = Path(origem)

        if not origem.exists():

            self.mostrar_toast(
                "A pasta não existe mais.",
                "erro",
            )

            return

        if origem.name == novo_nome:

            self.mostrar_toast(
                "A pasta já possui esse nome.",
                "info",
            )

            return

        destino = (
            origem.parent
            / novo_nome
        )

        # ----------------------------------------
        # RENOMEAÇÃO SIMPLES
        # ----------------------------------------

        if not destino.exists():

            try:
                origem.rename(
                    destino
                )

                # ATUALIZA IMEDIATAMENTE O ITEM
                tree_item.setText(
                    0,
                    novo_nome,
                )

                tree_item.setText(
                    1,
                    "CORRETA",
                )

                tree_item.setForeground(
                    0,
                    QColor(COR_OK),
                )

                tree_item.setForeground(
                    1,
                    QColor(COR_OK),
                )

                tree_item.setData(
                    0,
                    Qt.UserRole,
                    str(destino),
                )

                # Recria os botões usando o novo caminho
                self.adicionar_acoes_pasta(
                    tree_item,
                    destino,
                    projeto_item,
                )

                # atualiza apenas os filhos deste projeto
                self.atualizar_projeto_item(
                    projeto_item,
                    destino.parent,
                )

                self.mostrar_toast(
                    f"Renomeada para {novo_nome}",
                    "sucesso",
                )

            except Exception as erro:

                self.mostrar_toast(
                    f"Erro ao renomear: {erro}",
                    "erro",
                )

            return

        # ----------------------------------------
        # DESTINO JÁ EXISTE
        # ----------------------------------------

        resposta = QMessageBox.question(
            self,
            "Pasta já existente",
            (
                f"A pasta:\n\n{novo_nome}\n\n"
                "já existe.\n\n"
                "Deseja mesclar o conteúdo?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if resposta != QMessageBox.Yes:
            return

        self.mesclar_pastas(
            origem,
            destino,
            projeto_item,
        )

    # ======================================================
    # MESCLAGEM
    # ======================================================

    def mesclar_pastas(
        self,
        origem,
        destino,
        projeto_item,
    ):

        conflitos = []

        try:

            for item in list(
                origem.iterdir()
            ):

                destino_item = (
                    destino
                    / item.name
                )

                if not destino_item.exists():

                    shutil.move(
                        str(item),
                        str(destino_item),
                    )

                elif (
                    item.is_dir()
                    and destino_item.is_dir()
                ):

                    self.mesclar_diretorio_recursivo(
                        item,
                        destino_item,
                        conflitos,
                    )

                else:

                    conflitos.append(
                        str(item)
                    )

            try:
                if not any(
                    origem.iterdir()
                ):
                    origem.rmdir()

            except Exception:
                pass

            self.atualizar_projeto_item(
                projeto_item,
                destino.parent,
            )

            if conflitos:

                self.mostrar_toast(
                    (
                        f"Mesclado com "
                        f"{len(conflitos)} conflito(s)."
                    ),
                    "aviso",
                )

            else:

                self.mostrar_toast(
                    "Pastas mescladas com sucesso.",
                    "sucesso",
                )

        except Exception as erro:

            self.mostrar_toast(
                f"Erro na mesclagem: {erro}",
                "erro",
            )

    def mesclar_diretorio_recursivo(
        self,
        origem,
        destino,
        conflitos,
    ):

        destino.mkdir(
            parents=True,
            exist_ok=True,
        )

        for item in list(
            origem.iterdir()
        ):

            alvo = (
                destino
                / item.name
            )

            if not alvo.exists():

                shutil.move(
                    str(item),
                    str(alvo),
                )

            elif (
                item.is_dir()
                and alvo.is_dir()
            ):

                self.mesclar_diretorio_recursivo(
                    item,
                    alvo,
                    conflitos,
                )

            else:

                conflitos.append(
                    str(item)
                )

        try:
            if not any(
                origem.iterdir()
            ):
                origem.rmdir()

        except Exception:
            pass

    # ======================================================
    # ESTATÍSTICAS
    # ======================================================

    def carregar_estatisticas(
        self,
        item,
        caminho,
    ):

        worker = EstatisticasWorker(
            item,
            caminho,
        )

        worker.signals.finalizado.connect(
            self.estatisticas_finalizadas
        )

        self.thread_pool.start(
            worker
        )

    def estatisticas_finalizadas(
        self,
        item,
        caminho_original,
        arquivos,
        subpastas,
        tamanho,
    ):

        try:

            # Impede thread antiga de atualizar
            # um item que já mudou de caminho.
            caminho_atual = item.data(
                0,
                Qt.UserRole,
            )

            if (
                caminho_atual
                and caminho_atual
                != caminho_original
            ):
                return

            item.setText(
                2,
                f"{arquivos:,}".replace(
                    ",",
                    ".",
                ),
            )

            item.setText(
                3,
                f"{subpastas:,}".replace(
                    ",",
                    ".",
                ),
            )

            item.setText(
                4,
                formatar_tamanho(
                    tamanho
                ),
            )

        except RuntimeError:
            pass

    # ======================================================
    # FILTRO
    # ======================================================

    def filtrar_projetos(
        self,
        texto,
    ):

        texto = (
            texto.lower().strip()
        )

        for i in range(
            self.tree.topLevelItemCount()
        ):

            item = (
                self.tree.topLevelItem(i)
            )

            nome = (
                item.text(0).lower()
            )

            mostrar = (
                not texto
                or texto in nome
            )

            item.setHidden(
                not mostrar
            )

            if (
                texto
                and mostrar
            ):
                item.setExpanded(
                    True
                )

    # ======================================================
    # PASTA MÃE
    # ======================================================

    def selecionar_pasta_mae(self):

        pasta = (
            QFileDialog.getExistingDirectory(
                self,
                "Selecionar pasta mãe",
                str(self.pasta_mae),
            )
        )

        if not pasta:
            return

        self.pasta_mae = Path(
            pasta
        )

        self.input_pasta.setText(
            pasta
        )

        self.carregar_projetos(
            exibir_toast=True
        )

    # ======================================================
    # DUPLO CLIQUE
    # ======================================================

    def duplo_clique_item(
        self,
        item,
        coluna,
    ):

        caminho = item.data(
            0,
            Qt.UserRole,
        )

        if not caminho:
            return

        caminho = Path(
            caminho
        )

        if caminho.exists():
            abrir_explorer(
                caminho
            )

    # ======================================================
    # ESTILO
    # ======================================================

    def aplicar_estilo(self):

        self.setStyleSheet(
            f"""
            QMainWindow {{
                background-color: {COR_FUNDO};
            }}

            QWidget {{
                background-color: {COR_FUNDO};
                color: {COR_TEXTO};
                font-family: "Segoe UI";
                font-size: 10pt;
            }}

            #header {{
                background-color: {COR_PAINEL};
                border: 1px solid {COR_BORDA};
                border-left: 4px solid {COR_DOURADO};
                border-radius: 8px;
                padding: 10px;
            }}

            #titulo {{
                color: {COR_DOURADO_CLARO};
                font-size: 17pt;
                font-weight: 700;
            }}

            #subtitulo {{
                color: {COR_TEXTO_SECUNDARIO};
            }}

            #card {{
                background-color: {COR_PAINEL};
                border: 1px solid {COR_BORDA};
                border-radius: 8px;
                min-width: 150px;
                padding: 5px;
            }}

            #cardTitulo {{
                color: {COR_TEXTO_SECUNDARIO};
                font-size: 9pt;
            }}

            #cardValor {{
                color: {COR_DOURADO_CLARO};
                font-size: 18pt;
                font-weight: bold;
            }}

            QPushButton,
            QToolButton {{
                background-color: {COR_PAINEL_2};
                border: 1px solid #444444;
                color: {COR_TEXTO};
                border-radius: 5px;
                padding: 7px 12px;
            }}

            QPushButton:hover,
            QToolButton:hover {{
                border-color: {COR_DOURADO};
                color: {COR_DOURADO_CLARO};
                background-color: #292929;
            }}

            #btnPrincipal {{
                background-color: {COR_DOURADO};
                color: #111111;
                border: 1px solid {COR_DOURADO};
                font-weight: bold;
            }}

            #btnPrincipal:hover {{
                background-color: {COR_DOURADO_CLARO};
            }}

            QLineEdit {{
                background-color: {COR_PAINEL};
                border: 1px solid {COR_BORDA};
                border-radius: 6px;
                padding: 8px;
            }}

            QLineEdit:focus {{
                border: 1px solid {COR_DOURADO};
            }}

            QTreeWidget {{
                background-color: {COR_PAINEL};
                border: 1px solid {COR_BORDA};
                border-radius: 8px;
                outline: none;
            }}

            QTreeWidget::item {{
                height: 38px;
                border-bottom: 1px solid #252525;
            }}

            QTreeWidget::item:selected {{
                background-color: #3A321B;
            }}

            QTreeWidget::item:hover {{
                background-color: #242424;
            }}

            QHeaderView::section {{
                background-color: #202020;
                color: {COR_DOURADO_CLARO};
                padding: 9px;
                border: none;
                border-right: 1px solid #333333;
                border-bottom: 1px solid {COR_DOURADO};
                font-weight: bold;
            }}

            QMenu {{
                background-color: #202020;
                border: 1px solid {COR_DOURADO};
                padding: 5px;
            }}

            QMenu::item {{
                padding: 8px 25px;
                border-radius: 4px;
            }}

            QMenu::item:selected {{
                background-color: #3A321B;
                color: {COR_DOURADO_CLARO};
            }}

            QScrollBar:vertical {{
                background-color: #161616;
                width: 12px;
            }}

            QScrollBar::handle:vertical {{
                background-color: #444444;
                min-height: 30px;
                border-radius: 6px;
            }}

            QScrollBar::handle:vertical:hover {{
                background-color: {COR_DOURADO};
            }}

            QScrollBar:add-line:vertical,
            QScrollBar:sub-line:vertical {{
                height: 0;
            }}

            #legenda {{
                color: {COR_TEXTO_SECUNDARIO};
                padding: 5px;
            }}
            """
        )


# ==========================================================
# MAIN
# ==========================================================

def main():

    app = QApplication(
        sys.argv
    )

    app.setStyle(
        "Fusion"
    )

    janela = GerenciadorPastas()

    janela.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()