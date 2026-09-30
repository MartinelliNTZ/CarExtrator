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
    QSize,
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
)


# ==========================================================
# CONFIGURAÇÕES
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

COR_OK = "#5CB85C"
COR_ERRO = "#E85D5D"
COR_AVISO = "#E6A23C"
COR_AZUL = "#5B9BD5"


# ==========================================================
# FUNÇÕES AUXILIARES
# ==========================================================

def formatar_tamanho(bytes_total: int) -> str:
    """Converte bytes para unidade legível."""
    unidades = ["B", "KB", "MB", "GB", "TB"]

    tamanho = float(bytes_total)

    for unidade in unidades:
        if tamanho < 1024:
            if unidade in ("GB", "TB"):
                return f"{tamanho:.2f} {unidade}"
            return f"{tamanho:.1f} {unidade}"

        tamanho /= 1024

    return f"{tamanho:.2f} PB"


def obter_estatisticas_pasta(caminho: Path):
    """
    Conta recursivamente:
    - arquivos
    - subpastas
    - bytes
    """

    arquivos = 0
    subpastas = 0
    tamanho = 0

    try:
        for raiz, dirs, files in os.walk(caminho):
            subpastas += len(dirs)
            arquivos += len(files)

            for nome_arquivo in files:
                arquivo = Path(raiz) / nome_arquivo

                try:
                    tamanho += arquivo.stat().st_size
                except (PermissionError, FileNotFoundError, OSError):
                    pass

    except (PermissionError, FileNotFoundError, OSError):
        pass

    return arquivos, subpastas, tamanho


def abrir_explorer(caminho: Path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(caminho))
        else:
            import subprocess

            if sys.platform == "darwin":
                subprocess.Popen(["open", str(caminho)])
            else:
                subprocess.Popen(["xdg-open", str(caminho)])

    except Exception as erro:
        QMessageBox.critical(
            None,
            "Erro",
            f"Não foi possível abrir a pasta:\n\n{erro}",
        )


# ==========================================================
# WORKER PARA ESTATÍSTICAS
# ==========================================================

class WorkerSignals(QObject):
    finalizado = Signal(object, int, int, int)


class EstatisticasWorker(QRunnable):
    def __init__(self, item, caminho):
        super().__init__()

        self.item = item
        self.caminho = Path(caminho)
        self.signals = WorkerSignals()

    def run(self):
        arquivos, subpastas, tamanho = obter_estatisticas_pasta(
            self.caminho
        )

        self.signals.finalizado.emit(
            self.item,
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

        self.thread_pool = QThreadPool.globalInstance()

        self.setWindowTitle(
            "AGROROBÓTICA | Gerenciador de Estrutura VERRA Farmer"
        )

        self.resize(1500, 900)
        self.setMinimumSize(1100, 650)

        self.criar_interface()
        self.aplicar_estilo()

        self.carregar_projetos()

    # ======================================================
    # INTERFACE
    # ======================================================

    def criar_interface(self):

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # --------------------------------------------------
        # CABEÇALHO
        # --------------------------------------------------

        header = QFrame()
        header.setObjectName("header")

        header_layout = QVBoxLayout(header)

        titulo = QLabel("GERENCIADOR DE ESTRUTURA DE PROJETOS")
        titulo.setObjectName("titulo")

        subtitulo = QLabel(
            "VERRA Farmer • Conferência e padronização de diretórios"
        )
        subtitulo.setObjectName("subtitulo")

        header_layout.addWidget(titulo)
        header_layout.addWidget(subtitulo)

        layout.addWidget(header)

        # --------------------------------------------------
        # PASTA MÃE
        # --------------------------------------------------

        barra = QHBoxLayout()

        label_pasta = QLabel("Pasta mãe:")

        self.input_pasta = QLineEdit(
            str(self.pasta_mae)
        )

        self.input_pasta.setReadOnly(True)

        btn_escolher = QPushButton("Selecionar pasta")
        btn_escolher.clicked.connect(
            self.selecionar_pasta_mae
        )

        self.btn_atualizar = QPushButton("↻ Atualizar")
        self.btn_atualizar.setObjectName("btnPrincipal")
        self.btn_atualizar.clicked.connect(
            self.carregar_projetos
        )

        barra.addWidget(label_pasta)
        barra.addWidget(self.input_pasta, 1)
        barra.addWidget(btn_escolher)
        barra.addWidget(self.btn_atualizar)

        layout.addLayout(barra)

        # --------------------------------------------------
        # RESUMO
        # --------------------------------------------------

        resumo = QHBoxLayout()

        self.lbl_projetos = self.criar_card(
            "Projetos", "0"
        )

        self.lbl_corretas = self.criar_card(
            "Pastas corretas", "0"
        )

        self.lbl_incorretas = self.criar_card(
            "Incoerentes", "0"
        )

        self.lbl_ausentes = self.criar_card(
            "Ausentes", "0"
        )

        resumo.addWidget(self.lbl_projetos["frame"])
        resumo.addWidget(self.lbl_corretas["frame"])
        resumo.addWidget(self.lbl_incorretas["frame"])
        resumo.addWidget(self.lbl_ausentes["frame"])

        layout.addLayout(resumo)

        # --------------------------------------------------
        # FILTRO
        # --------------------------------------------------

        filtro_layout = QHBoxLayout()

        lbl = QLabel("Pesquisar projeto:")

        self.input_pesquisa = QLineEdit()
        self.input_pesquisa.setPlaceholderText(
            "Digite parte do nome da pasta/projeto..."
        )

        self.input_pesquisa.textChanged.connect(
            self.filtrar_projetos
        )

        filtro_layout.addWidget(lbl)
        filtro_layout.addWidget(
            self.input_pesquisa,
            1,
        )

        layout.addLayout(filtro_layout)

        # --------------------------------------------------
        # TREE
        # --------------------------------------------------

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

        self.tree.setAlternatingRowColors(False)
        self.tree.setAnimated(True)
        self.tree.setIndentation(24)

        header = self.tree.header()

        header.setSectionResizeMode(
            0,
            QHeaderView.Stretch,
        )

        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeToContents,
        )

        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeToContents,
        )

        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeToContents,
        )

        header.setSectionResizeMode(
            4,
            QHeaderView.ResizeToContents,
        )

        header.setSectionResizeMode(
            5,
            QHeaderView.Fixed,
        )

        self.tree.setColumnWidth(5, 310)

        self.tree.itemDoubleClicked.connect(
            self.duplo_clique_item
        )

        layout.addWidget(
            self.tree,
            1,
        )

        # --------------------------------------------------
        # LEGENDA
        # --------------------------------------------------

        legenda = QLabel(
            "● Verde = padrão correto     "
            "● Vermelho = nome incoerente     "
            "● Laranja = pasta padrão ausente"
        )

        legenda.setObjectName("legenda")

        layout.addWidget(legenda)

    # ======================================================
    # CARD
    # ======================================================

    def criar_card(self, titulo, valor):

        frame = QFrame()
        frame.setObjectName("card")

        layout = QVBoxLayout(frame)

        titulo_label = QLabel(titulo)
        titulo_label.setObjectName("cardTitulo")

        valor_label = QLabel(valor)
        valor_label.setObjectName("cardValor")

        layout.addWidget(titulo_label)
        layout.addWidget(valor_label)

        return {
            "frame": frame,
            "valor": valor_label,
        }

    # ======================================================
    # CARREGAMENTO
    # ======================================================

    def carregar_projetos(self):

        caminho_texto = self.input_pasta.text().strip()

        if caminho_texto:
            self.pasta_mae = Path(caminho_texto)

        if not self.pasta_mae.exists():

            QMessageBox.warning(
                self,
                "Pasta não encontrada",
                f"A pasta mãe não existe:\n\n{self.pasta_mae}",
            )

            return

        self.tree.clear()

        projetos = sorted(
            [
                item
                for item in self.pasta_mae.iterdir()
                if item.is_dir()
            ],
            key=lambda x: x.name.lower(),
        )

        total_corretas = 0
        total_incorretas = 0
        total_ausentes = 0

        for projeto in projetos:

            projeto_item = self.criar_item_projeto(
                projeto
            )

            (
                corretas,
                incorretas,
                ausentes,
            ) = self.carregar_pastas_projeto(
                projeto_item,
                projeto,
            )

            total_corretas += corretas
            total_incorretas += incorretas
            total_ausentes += ausentes

            self.carregar_estatisticas(
                projeto_item,
                projeto,
            )

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

    # ======================================================
    # ITEM PROJETO
    # ======================================================

    def criar_item_projeto(self, projeto):

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

        item.setText(
            2,
            "...",
        )

        item.setText(
            3,
            "...",
        )

        item.setText(
            4,
            "...",
        )

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
        fonte.setPointSize(10)

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

        widget_acoes = QWidget()

        layout = QHBoxLayout(
            widget_acoes
        )

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

        btn_adicionar = QToolButton()

        btn_adicionar.setText(
            "+ Adicionar pasta"
        )

        btn_adicionar.setPopupMode(
            QToolButton.InstantPopup
        )

        menu = self.criar_menu_adicionar(
            projeto
        )

        btn_adicionar.setMenu(
            menu
        )

        layout.addWidget(
            btn_abrir
        )

        layout.addWidget(
            btn_adicionar
        )

        self.tree.setItemWidget(
            item,
            5,
            widget_acoes,
        )

        return item

    # ======================================================
    # PASTAS DO PROJETO
    # ======================================================

    def carregar_pastas_projeto(
        self,
        projeto_item,
        projeto,
    ):

        try:
            pastas_existentes = sorted(
                [
                    p
                    for p in projeto.iterdir()
                    if p.is_dir()
                ],
                key=lambda x: x.name.lower(),
            )

        except Exception:
            pastas_existentes = []

        nomes_existentes = {
            p.name
            for p in pastas_existentes
        }

        corretas = 0
        incorretas = 0

        # --------------------------------------------------
        # PASTAS EXISTENTES
        # --------------------------------------------------

        for pasta in pastas_existentes:

            if pasta.name in PASTAS_PADRAO:

                status = "CORRETA"
                cor = COR_OK

                corretas += 1

            else:

                status = "INCOERENTE"
                cor = COR_ERRO

                incorretas += 1

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

            item.setText(
                2,
                "...",
            )

            item.setText(
                3,
                "...",
            )

            item.setText(
                4,
                "...",
            )

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
            )

            self.carregar_estatisticas(
                item,
                pasta,
            )

        # --------------------------------------------------
        # PASTAS PADRÃO QUE NÃO EXISTEM
        # --------------------------------------------------

        faltantes = [
            nome
            for nome in PASTAS_PADRAO
            if nome not in nomes_existentes
        ]

        for nome_padrao in faltantes:

            item = QTreeWidgetItem(
                projeto_item
            )

            item.setText(
                0,
                nome_padrao,
            )

            item.setText(
                1,
                "AUSENTE",
            )

            item.setText(
                2,
                "—",
            )

            item.setText(
                3,
                "—",
            )

            item.setText(
                4,
                "—",
            )

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
                nome=nome_padrao:
                self.criar_pasta(
                    projeto,
                    nome,
                )
            )

            self.tree.setItemWidget(
                item,
                5,
                btn,
            )

        return (
            corretas,
            incorretas,
            len(faltantes),
        )

    # ======================================================
    # AÇÕES DA PASTA
    # ======================================================

    def adicionar_acoes_pasta(
        self,
        item,
        pasta,
    ):

        widget = QWidget()

        layout = QHBoxLayout(widget)

        layout.setContentsMargins(
            2,
            2,
            2,
            2,
        )

        layout.setSpacing(5)

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

        for nome_padrao in PASTAS_PADRAO:

            acao = menu.addAction(
                nome_padrao
            )

            acao.triggered.connect(
                lambda checked=False,
                origem=pasta,
                destino=nome_padrao:
                self.renomear_pasta(
                    origem,
                    destino,
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
    # MENU DE ADICIONAR
    # ======================================================

    def criar_menu_adicionar(
        self,
        projeto,
    ):

        menu = QMenu(self)

        for nome in PASTAS_PADRAO:

            acao = menu.addAction(
                nome
            )

            acao.triggered.connect(
                lambda checked=False,
                p=projeto,
                n=nome:
                self.criar_pasta(
                    p,
                    n,
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
    ):

        destino = projeto / nome

        if destino.exists():

            QMessageBox.information(
                self,
                "Pasta existente",
                (
                    "Essa pasta já existe no projeto:\n\n"
                    f"{nome}"
                ),
            )

            return

        try:

            destino.mkdir(
                parents=False,
                exist_ok=False,
            )

            QMessageBox.information(
                self,
                "Pasta criada",
                (
                    "Pasta criada com sucesso:\n\n"
                    f"{nome}"
                ),
            )

            self.carregar_projetos()

        except Exception as erro:

            QMessageBox.critical(
                self,
                "Erro",
                (
                    "Não foi possível criar a pasta.\n\n"
                    f"{erro}"
                ),
            )

    # ======================================================
    # RENOMEAR
    # ======================================================

    def renomear_pasta(
        self,
        origem,
        novo_nome,
    ):

        origem = Path(origem)

        if not origem.exists():

            QMessageBox.warning(
                self,
                "Pasta não encontrada",
                (
                    "A pasta de origem não existe mais.\n\n"
                    f"{origem}"
                ),
            )

            self.carregar_projetos()

            return

        if origem.name == novo_nome:
            return

        destino = origem.parent / novo_nome

        # --------------------------------------------------
        # DESTINO NÃO EXISTE
        # --------------------------------------------------

        if not destino.exists():

            try:

                origem.rename(
                    destino
                )

                self.carregar_projetos()

            except Exception as erro:

                QMessageBox.critical(
                    self,
                    "Erro ao renomear",
                    str(erro),
                )

            return

        # --------------------------------------------------
        # DESTINO JÁ EXISTE
        # --------------------------------------------------

        resposta = QMessageBox.question(
            self,
            "Pasta já existe",
            (
                f"A pasta padrão:\n\n"
                f"{novo_nome}\n\n"
                "já existe neste projeto.\n\n"
                "Deseja MESCLAR o conteúdo da pasta atual "
                "com a pasta existente?\n\n"
                "Arquivos com o mesmo nome NÃO serão "
                "sobrescritos automaticamente."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if resposta != QMessageBox.Yes:
            return

        self.mesclar_pastas(
            origem,
            destino,
        )

    # ======================================================
    # MESCLAR PASTAS
    # ======================================================

    def mesclar_pastas(
        self,
        origem,
        destino,
    ):

        conflitos = []

        try:

            for item in list(
                origem.iterdir()
            ):

                destino_item = (
                    destino / item.name
                )

                # ------------------------------------------
                # NÃO EXISTE NO DESTINO
                # ------------------------------------------

                if not destino_item.exists():

                    shutil.move(
                        str(item),
                        str(destino_item),
                    )

                    continue

                # ------------------------------------------
                # DUAS PASTAS
                # ------------------------------------------

                if (
                    item.is_dir()
                    and destino_item.is_dir()
                ):

                    self.mesclar_diretorio_recursivo(
                        item,
                        destino_item,
                        conflitos,
                    )

                # ------------------------------------------
                # ARQUIVO COM MESMO NOME
                # ------------------------------------------

                else:

                    conflitos.append(
                        str(item)
                    )

            # Remove origem apenas se ficou vazia

            try:
                if not any(
                    origem.iterdir()
                ):
                    origem.rmdir()
            except Exception:
                pass

            if conflitos:

                QMessageBox.warning(
                    self,
                    "Mesclagem concluída com conflitos",
                    (
                        "A maior parte do conteúdo foi "
                        "mesclada.\n\n"
                        f"{len(conflitos)} arquivo(s) ou "
                        "item(ns) não foram movidos porque "
                        "já existiam no destino.\n\n"
                        "A pasta original foi mantida caso "
                        "ainda contenha esses arquivos."
                    ),
                )

            else:

                QMessageBox.information(
                    self,
                    "Mesclagem concluída",
                    (
                        "As pastas foram mescladas "
                        "com sucesso."
                    ),
                )

            self.carregar_projetos()

        except Exception as erro:

            QMessageBox.critical(
                self,
                "Erro na mesclagem",
                (
                    "Não foi possível concluir "
                    "a mesclagem.\n\n"
                    f"{erro}"
                ),
            )

            self.carregar_projetos()

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

            alvo = destino / item.name

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
        arquivos,
        subpastas,
        tamanho,
    ):

        # O item pode ter sido removido se a árvore
        # foi recarregada enquanto a thread trabalhava.

        try:

            item.setText(
                2,
                f"{arquivos:,}".replace(",", "."),
            )

            item.setText(
                3,
                f"{subpastas:,}".replace(",", "."),
            )

            item.setText(
                4,
                formatar_tamanho(tamanho),
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

        texto = texto.lower().strip()

        for i in range(
            self.tree.topLevelItemCount()
        ):

            item = self.tree.topLevelItem(i)

            nome = item.text(
                0
            ).lower()

            visivel = (
                not texto
                or texto in nome
            )

            item.setHidden(
                not visivel
            )

            if texto and visivel:
                item.setExpanded(True)

    # ======================================================
    # SELEÇÃO DA PASTA
    # ======================================================

    def selecionar_pasta_mae(self):

        pasta = QFileDialog.getExistingDirectory(
            self,
            "Selecionar pasta mãe dos projetos",
            str(self.pasta_mae),
        )

        if not pasta:
            return

        self.pasta_mae = Path(
            pasta
        )

        self.input_pasta.setText(
            pasta
        )

        self.carregar_projetos()

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
                font-size: 10pt;
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

            QPushButton:pressed,
            QToolButton:pressed {{
                background-color: #333333;
            }}

            #btnPrincipal {{
                background-color: {COR_DOURADO};
                color: #111111;
                border: 1px solid {COR_DOURADO};
                font-weight: bold;
            }}

            #btnPrincipal:hover {{
                background-color: {COR_DOURADO_CLARO};
                color: #111111;
            }}

            QLineEdit {{
                background-color: {COR_PAINEL};
                border: 1px solid {COR_BORDA};
                border-radius: 6px;
                padding: 8px;
                selection-background-color: {COR_DOURADO};
                selection-color: #111111;
            }}

            QLineEdit:focus {{
                border: 1px solid {COR_DOURADO};
            }}

            QTreeWidget {{
                background-color: {COR_PAINEL};
                alternate-background-color: #1C1C1C;
                border: 1px solid {COR_BORDA};
                border-radius: 8px;
                outline: none;
            }}

            QTreeWidget::item {{
                height: 36px;
                border-bottom: 1px solid #252525;
            }}

            QTreeWidget::item:selected {{
                background-color: #3A321B;
                color: white;
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
                margin: 0;
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