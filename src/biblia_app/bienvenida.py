import os
import random
import webbrowser

import flet as ft

from biblia_app.idiomas import LANGUAGES, construir_saludo_bienvenida, get_language_config, get_language_theme


TIKTOK_URL = "https://www.tiktok.com/@jmgalmedina"
_RANDOM = random.SystemRandom()
_SALUDOS_PENDIENTES_POR_IDIOMA: dict[str, list[str]] = {}
_ULTIMO_SALUDO_POR_IDIOMA: dict[str, str] = {}


def _border_all(width: float, color: str) -> ft.Border:
    side = ft.BorderSide(width, color)
    return ft.Border(left=side, top=side, right=side, bottom=side)

def _padding_symmetric(horizontal: float = 0, vertical: float = 0) -> ft.Padding:
    return ft.Padding(left=horizontal, top=vertical, right=horizontal, bottom=vertical)


def _obtener_siguiente_saludo(language_code: str) -> str:
    saludos = list(get_language_config(language_code).get("welcome", {}).get("greetings", []))
    if not saludos:
        return construir_saludo_bienvenida(language_code, _RANDOM.randrange(105))

    pendientes = _SALUDOS_PENDIENTES_POR_IDIOMA.get(language_code)
    if not pendientes:
        pendientes = saludos.copy()
        _RANDOM.shuffle(pendientes)
        ultimo_saludo = _ULTIMO_SALUDO_POR_IDIOMA.get(language_code)
        if ultimo_saludo and len(pendientes) > 1 and pendientes[0] == ultimo_saludo:
            pendientes.append(pendientes.pop(0))
        _SALUDOS_PENDIENTES_POR_IDIOMA[language_code] = pendientes

    saludo = pendientes.pop(0)
    _ULTIMO_SALUDO_POR_IDIOMA[language_code] = saludo
    return saludo


def _crear_bandera(tipo: str) -> ft.Control:
    if tipo == "spain":
        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        height=10,
                        bgcolor="#C60B1E",
                        border_radius=ft.BorderRadius(top_left=6, top_right=6, bottom_left=0, bottom_right=0),
                    ),
                    ft.Container(height=14, bgcolor="#FFC400"),
                    ft.Container(
                        height=10,
                        bgcolor="#C60B1E",
                        border_radius=ft.BorderRadius(top_left=0, top_right=0, bottom_left=6, bottom_right=6),
                    ),
                ],
                spacing=0,
                tight=True,
            ),
            width=34,
            border=_border_all(1, "black"),
            border_radius=6,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
    if tipo == "catalonia":
        franjas = []
        colores = ["#F6D04D", "#C8102E"] * 4
        for color in colores:
            franjas.append(ft.Container(height=4, bgcolor=color))
        franjas[0].border_radius = ft.BorderRadius(top_left=6, top_right=6, bottom_left=0, bottom_right=0)
        franjas[-1].border_radius = ft.BorderRadius(top_left=0, top_right=0, bottom_left=6, bottom_right=6)
        return ft.Container(
            content=ft.Column(franjas, spacing=0, tight=True),
            width=34,
            border=_border_all(1, "black"),
            border_radius=6,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
    if tipo == "france":
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=11, bgcolor="#EF4135"),
                    ft.Container(width=11, bgcolor="#FFFFFF"),
                    ft.Container(width=11, bgcolor="#0055A4"),
                ],
                spacing=0,
                tight=True,
            ),
            height=34,
            border=_border_all(1, "black"),
            border_radius=6,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
    if tipo == "uk":
        return ft.Container(
            content=ft.Stack(
                [
                    ft.Container(bgcolor="#012169"),
                    ft.Container(bgcolor="#FFFFFF", rotate=ft.Rotate(angle=0.62), width=46, height=8, left=-6, top=13),
                    ft.Container(bgcolor="#FFFFFF", rotate=ft.Rotate(angle=-0.62), width=46, height=8, left=-6, top=13),
                    ft.Container(bgcolor="#C8102E", rotate=ft.Rotate(angle=0.62), width=46, height=4, left=-6, top=15),
                    ft.Container(bgcolor="#C8102E", rotate=ft.Rotate(angle=-0.62), width=46, height=4, left=-6, top=15),
                    ft.Container(height=10, bgcolor="#FFFFFF", top=12, left=0, right=0),
                    ft.Container(width=10, bgcolor="#FFFFFF", top=0, bottom=0, left=12),
                    ft.Container(height=6, bgcolor="#C8102E", top=14, left=0, right=0),
                    ft.Container(width=6, bgcolor="#C8102E", top=0, bottom=0, left=14),
                ]
            ),
            width=34,
            height=34,
            border=_border_all(1, "black"),
            border_radius=6,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
    return ft.Container(
        content=ft.Stack(
            [
                ft.Container(bgcolor="white"),
                ft.Container(height=8, bgcolor="#CE1126", top=13, left=0, right=0),
                ft.Container(width=8, bgcolor="#CE1126", top=0, bottom=0, left=13),
            ]
        ),
        width=34,
        height=34,
        border=_border_all(1, "black"),
        border_radius=6,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )


def _boton_idioma(language_code: str, on_select_language):
    cfg = get_language_config(language_code)
    theme = get_language_theme(language_code)
    texto_nombre = ft.Text(cfg["native_name"], weight="bold", size=16, color=theme["text"])
    boton = ft.ElevatedButton(
        content=ft.Row(
            [
                _crear_bandera(cfg["flag"]),
                texto_nombre,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=12,
        ),
        style=ft.ButtonStyle(
            bgcolor=theme["field_bg"],
            color=theme["text"],
            side=ft.BorderSide(4, theme["primary"]),
            shape=ft.RoundedRectangleBorder(radius=14),
            padding=20,
        ),
        width=320,
        height=88,
    )
    boton.data = {
        "language_code": language_code,
        "theme": theme,
        "label": texto_nombre,
    }
    return boton


def pantalla_selector_idioma(page: ft.Page, on_select_language):
    selector = get_language_config("es")["selector"]
    theme = get_language_theme("es")
    botones = [_boton_idioma(language_code, on_select_language) for language_code in LANGUAGES]
    seleccionando = {"code": None}

    def actualizar_estado_botones():
        for boton in botones:
            datos = boton.data
            tema_boton = datos["theme"]
            activo = seleccionando["code"] == datos["language_code"]
            bloqueado = seleccionando["code"] is not None and not activo
            datos["label"].color = "#FFFFFF" if activo else tema_boton["text"]
            boton.disabled = seleccionando["code"] is not None
            boton.style = ft.ButtonStyle(
                bgcolor=(tema_boton["primary"] if activo else ("#E0E0E0" if bloqueado else tema_boton["field_bg"])),
                color=("#FFFFFF" if activo else tema_boton["text"]),
                side=ft.BorderSide(5 if activo else 4, tema_boton["primary"] if not bloqueado else "#BDBDBD"),
                shape=ft.RoundedRectangleBorder(radius=14),
                padding=20,
            )

    def seleccionar_idioma(language_code: str):
        if seleccionando["code"] is not None:
            return
        seleccionando["code"] = language_code
        actualizar_estado_botones()
        page.update()
        on_select_language(language_code)

    for boton in botones:
        language_code = boton.data["language_code"]
        boton.on_click = lambda e, code=language_code: seleccionar_idioma(code)

    actualizar_estado_botones()
    textos_cabecera = [ft.Text("Biblia IA", size=30, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER)]
    if selector.get("title"):
        textos_cabecera.append(ft.Text(selector["title"], size=22, weight="bold", color=theme["text"], text_align=ft.TextAlign.CENTER))
    if selector.get("subtitle"):
        textos_cabecera.append(
            ft.Text(
                selector["subtitle"],
                size=17,
                italic=True,
                weight=ft.FontWeight.W_600,
                color=theme["text"],
                text_align=ft.TextAlign.CENTER,
            )
        )

    return ft.Column(
        controls=[
            ft.Icon(ft.Icons.LANGUAGE, color=theme["primary"], size=54),
            ft.Column(
                textos_cabecera,
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            ft.Divider(height=10, color="transparent"),
            *botones,
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=18,
        tight=True,
    )


def pantalla_saludos(page: ft.Page, language_code: str, on_continuar, on_volver=None):
    cfg = get_language_config(language_code)
    theme = get_language_theme(language_code)
    welcome = cfg["welcome"]
    es_frances = language_code == "fr"
    es_ingles = language_code == "en"

    def mostrar_error(texto: str):
        page.snack_bar = ft.SnackBar(ft.Text(texto))
        page.snack_bar.open = True
        page.update()

    def abrir_tiktok(_):
        ultimo_error = None

        try:
            page.launch_url(TIKTOK_URL)
            return
        except Exception as exc:
            ultimo_error = exc

        try:
            os.startfile(TIKTOK_URL)
            return
        except Exception as exc:
            ultimo_error = exc

        try:
            if webbrowser.open(TIKTOK_URL, new=2):
                return
        except Exception as exc:
            ultimo_error = exc

        mostrar_error(welcome["snackbar_open_error"].format(error=ultimo_error))

    controles = [
        ft.Icon(ft.Icons.AUTO_STORIES, color=theme["primary"], size=54),
        ft.Text(welcome["title"], size=28, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER),
        ft.Row(
            [
                _crear_bandera(cfg["flag"]),
                ft.Text(cfg["native_name"], size=18, weight="bold", color=theme["text"]),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
        ),
        ft.Text(welcome["subtitle"], size=14, color=theme["muted"], text_align=ft.TextAlign.CENTER),
        ft.Divider(height=20, color="transparent"),
        ft.ElevatedButton(
            welcome["follow"],
            url=TIKTOK_URL,
            on_click=abrir_tiktok,
            style=ft.ButtonStyle(
                bgcolor=("#EF4135" if es_frances else "#012169") if (es_frances or es_ingles) else theme["secondary"],
                color="#FFFFFF" if (es_frances or es_ingles) else theme["secondary_text"],
                side=ft.BorderSide(4, theme["border"]),
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
            width=300,
            height=60,
        ),
        ft.ElevatedButton(
            welcome["continue"],
            on_click=lambda e: on_continuar(),
            style=ft.ButtonStyle(
                bgcolor="#FFFFFF" if (es_frances or es_ingles) else theme["primary"],
                color="#10233C" if (es_frances or es_ingles) else theme["primary_text"],
                side=ft.BorderSide(4, theme["border"]),
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
            width=300,
            height=60,
        ),
    ]

    if on_volver is not None:
        controles.append(
            ft.OutlinedButton(
                welcome["back"],
                on_click=lambda e: on_volver(),
                style=ft.ButtonStyle(
                    color="#FFFFFF" if (es_frances or es_ingles) else theme["text"],
                    side=ft.BorderSide(3, theme["primary"]),
                    shape=ft.RoundedRectangleBorder(radius=10),
                    bgcolor=("#0055A4" if es_frances else "#C8102E") if (es_frances or es_ingles) else theme["field_bg"],
                    padding=_padding_symmetric(horizontal=18, vertical=12),
                ),
                width=300,
                height=60,
            )
        )

    return ft.Column(
        controls=controles,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=20,
        tight=True,
    )


def pantalla_selector_modo(page: ft.Page, language_code: str, on_select_mode, on_volver=None):
    cfg = get_language_config(language_code)
    theme = get_language_theme(language_code)
    ui = cfg["ui"]
    titulo_seleccion = {
        "es": "SELECCIÓN",
        "ca": "SELECCIO",
        "fr": "SELECTION",
        "en": "SELECTION",
    }.get(language_code, "SELECCIÓN")
    texto_biblia = {
        "es": ("BIBLIA", "COMENTARIO BÍBLICO"),
        "ca": ("BIBLIA", "COMENTARI BIBLIC"),
        "fr": ("BIBLE", "COMMENTAIRE BIBLIQUE"),
        "en": ("BIBLE", "BIBLICAL COMMENTARY"),
    }.get(language_code, ("BIBLIA", "COMENTARIO BÍBLICO"))
    texto_estudio = {
        "es": ("ESTUDIO BÍBLICO", "TEMAS, PERSONAJES, PUEBLOS, ETC"),
        "ca": ("ESTUDI BIBLIC", "TEMES, PERSONATGES, POBLES, ETC"),
        "fr": ("ETUDE BIBLIQUE", "THEMES, PERSONNAGES, PEUPLES, ETC"),
        "en": ("BIBLICAL STUDY", "TOPICS, CHARACTERS, PEOPLES, ETC"),
    }.get(language_code, ("ESTUDIO BÍBLICO", "TEMAS, PERSONAJES, PUEBLOS, ETC"))
    texto_comportamiento = {
        "es": ("CÓMO COMPORTARME SI...", "CRÍTICAS, ENFADOS, CONFLICTOS, ETC"),
        "ca": ("COM COMPORTAR-ME SI...", "CRITIQUES, ENFADAMENTS, CONFLICTES, ETC"),
        "fr": ("COMMENT ME COMPORTER SI...", "CRITIQUES, COLERES, CONFLITS, ETC"),
        "en": ("HOW SHOULD I RESPOND IF...", "CRITICISM, ANGER, CONFLICTS, ETC"),
    }.get(language_code, ("CÓMO COMPORTARME SI...", "CRÍTICAS, ENFADOS, CONFLICTOS, ETC"))
    texto_incredulo = {
        "es": ("QUÉ RESPONDER A UN INCRÉDULO SI...", "PREGUNTAS DIFÍCILES, FE, BIBLIA, DIOS, ETC"),
        "ca": ("QUE RESPONDRE A UN INCREDUL SI...", "PREGUNTES DIFICILS, FE, BIBLIA, DEU, ETC"),
        "fr": ("QUE REPONDRE A UN INCREDULE SI...", "QUESTIONS DIFFICILES, FOI, BIBLE, DIEU, ETC"),
        "en": ("WHAT TO ANSWER AN UNBELIEVER IF...", "HARD QUESTIONS, FAITH, BIBLE, GOD, ETC"),
    }.get(language_code, ("QUÉ RESPONDER A UN INCRÉDULO SI...", "PREGUNTAS DIFÍCILES, FE, BIBLIA, DIOS, ETC"))
    texto_cristianos = {
        "es": ("PREGUNTAS QUE LOS CRISTIANOS NOS HACEMOS", "DUDAS DE FE, ORACION, PRUEBAS, GUIA DE DIOS, ETC"),
        "ca": ("PREGUNTES QUE ELS CRISTIANS ENS FEM", "DUBTES DE FE, ORACIO, PROVES, GUIA DE DEU, ETC"),
        "fr": ("QUESTIONS QUE LES CHRETIENS SE POSENT", "DOUTES, PRIERE, EPREUVES, DIRECTION DE DIEU, ETC"),
        "en": ("QUESTIONS CHRISTIANS ASK", "FAITH DOUBTS, PRAYER, TRIALS, GOD'S GUIDANCE, ETC"),
    }.get(language_code, ("PREGUNTAS QUE LOS CRISTIANOS NOS HACEMOS", "DUDAS DE FE, ORACION, PRUEBAS, GUIA DE DIOS, ETC"))
    texto_preguntas = {
        "es": ("PREGUNTAS", ""),
        "ca": ("PREGUNTES", ""),
        "fr": ("QUESTIONS", ""),
        "en": ("QUESTIONS", ""),
    }.get(language_code, ("PREGUNTAS", ""))
    texto_chat_consejero = {
        "es": ("CHAT CONSEJERO CRISTIANO", ""),
        "ca": ("XAT CONSELLER CRISTIÀ", ""),
        "fr": ("CHAT CONSEILLER CHRÉTIEN", ""),
        "en": ("CHRISTIAN COUNSELOR CHAT", ""),
    }.get(language_code, ("CHAT CONSEJERO CRISTIANO", ""))
    texto_chat_suenos = {
        "es": ("CHAT INTERPRETACIÓN DE SUEÑOS", ""),
        "ca": ("XAT INTERPRETACIÓ DE SOMNIS", ""),
        "fr": ("CHAT INTERPRÉTATION DES RÊVES", ""),
        "en": ("DREAM INTERPRETATION CHAT", ""),
    }.get(language_code, ("CHAT INTERPRETACIÓN DE SUEÑOS", ""))
    texto_dones = {
        "es": ("TEST DE DONES ESPIRITUALES", ""),
        "ca": ("TEST DE DONES ESPIRITUALS", ""),
        "fr": ("TEST DES DONS SPIRITUELS", ""),
        "en": ("SPIRITUAL GIFTS TEST", ""),
    }.get(language_code, ("TEST DE DONES ESPIRITUALES", ""))
    texto_chat_soporte = {
        "es": ("GUÍA DE LA APP", ""),
        "ca": ("GUIA DE L'APP", ""),
        "fr": ("GUIDE DE L'APP", ""),
        "en": ("APP GUIDE", ""),
    }.get(language_code, ("GUÍA DE LA APP", ""))
    textos = {
        "es": {
            "title": "¿Cómo quieres empezar?",
            "subtitle": "Elige si quieres buscar un pasaje bíblico o hacer un estudio por tema, personaje, lugar y otros filtros.",
            "bible": "BIBLIA",
            "bible_help": "Ir al recuadro de pasaje bíblico",
            "study": "ESTUDIO",
            "study_help": "Ir al recuadro de tema, personaje, lugar y filtros",
            "back": "VOLVER",
        },
        "ca": {
            "title": "Com vols començar?",
            "subtitle": "Tria si vols cercar un passatge bíblic o fer un estudi per tema, personatge, lloc i altres filtres.",
            "bible": "BÍBLIA",
            "bible_help": "Anar al requadre de passatge bíblic",
            "study": "ESTUDI",
            "study_help": "Anar al requadre de tema, personatge, lloc i filtres",
            "back": "TORNAR",
        },
        "fr": {
            "title": "Comment veux-tu commencer ?",
            "subtitle": "Choisis si tu veux chercher un passage biblique ou faire une étude par thème, personnage, lieu et autres filtres.",
            "bible": "BIBLE",
            "bible_help": "Aller au cadre du passage biblique",
            "study": "ETUDE",
            "study_help": "Aller au cadre du thème, personnage, lieu et filtres",
            "back": "RETOUR",
        },
        "en": {
            "title": "How do you want to start?",
            "subtitle": "Choose whether you want to search a Bible passage or start a study by topic, character, place, and other filters.",
            "bible": "BIBLE",
            "bible_help": "Go to the Bible passage panel",
            "study": "STUDY",
            "study_help": "Go to the topic, character, place, and filters panel",
            "back": "BACK",
        },
    }.get(language_code, {
        "title": "¿Cómo quieres empezar?",
        "subtitle": "Elige si quieres buscar un pasaje bíblico o hacer un estudio por tema, personaje, lugar y otros filtros.",
        "bible": "BIBLIA",
        "bible_help": "Ir al recuadro de pasaje bíblico",
        "study": "ESTUDIO",
        "study_help": "Ir al recuadro de tema, personaje, lugar y filtros",
        "back": "VOLVER",
    })

    colores_botones = {
        "es": [
            ("#C60B1E", "#FFFFFF"),
            ("#FFC400", "#2F1B00"),
            ("#C60B1E", "#FFFFFF"),
            ("#FFC400", "#2F1B00"),
            ("#C60B1E", "#FFFFFF"),
            ("#FFC400", "#2F1B00"),
            ("#C60B1E", "#FFFFFF"),
        ],
        "ca": [
            ("#C8102E", "#FFFFFF"),
            ("#F6D04D", "#351600"),
            ("#C8102E", "#FFFFFF"),
            ("#F6D04D", "#351600"),
            ("#C8102E", "#FFFFFF"),
            ("#F6D04D", "#351600"),
            ("#C8102E", "#FFFFFF"),
        ],
        "fr": [
            ("#0055A4", "#FFFFFF"),
            ("#FFFFFF", "#1A2A44"),
            ("#EF4135", "#FFFFFF"),
            ("#0055A4", "#FFFFFF"),
            ("#EF4135", "#FFFFFF"),
            ("#0055A4", "#FFFFFF"),
            ("#EF4135", "#FFFFFF"),
        ],
        "en": [
            ("#012169", "#FFFFFF"),
            ("#FFFFFF", "#12264A"),
            ("#C8102E", "#FFFFFF"),
            ("#012169", "#FFFFFF"),
            ("#C8102E", "#FFFFFF"),
            ("#012169", "#FFFFFF"),
            ("#C8102E", "#FFFFFF"),
        ],
    }.get(language_code, [
        (theme["primary"], theme["primary_text"]),
        (theme["secondary"], theme["secondary_text"]),
        (theme["primary"], theme["primary_text"]),
        (theme["secondary"], theme["secondary_text"]),
        (theme["primary"], theme["primary_text"]),
        (theme["primary"], theme["primary_text"]),
        (theme["secondary"], theme["secondary_text"]),
    ])

    def boton_modo(texto, ayuda, icono, color_fondo, color_texto, accion):
        contenido = [
            ft.Icon(icono, size=28, color=color_texto),
            ft.Text(texto, size=16, weight="bold", color=color_texto, text_align=ft.TextAlign.CENTER),
        ]
        if ayuda:
            contenido.append(ft.Text(ayuda, size=11, color=color_texto, text_align=ft.TextAlign.CENTER))
        return ft.ElevatedButton(
            content=ft.Column(
                contenido,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=5,
                tight=True,
            ),
            on_click=lambda e: accion(),
            style=ft.ButtonStyle(
                bgcolor=color_fondo,
                color=color_texto,
                side=ft.BorderSide(4, theme["border"]),
                shape=ft.RoundedRectangleBorder(radius=16),
                padding=10,
            ),
            width=286,
            height=92,
        )

    controles = [
        ft.Icon(ft.Icons.EXPLORE, color=theme["primary"], size=44),
        ft.Text(cfg["welcome"]["title"], size=24, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER),
        ft.Text(titulo_seleccion, size=20, weight="bold", color=theme["text"], text_align=ft.TextAlign.CENTER),
        ft.Divider(height=4, color="transparent"),
        boton_modo(texto_chat_soporte[0], texto_chat_soporte[1], ft.Icons.HELP_OUTLINE, colores_botones[0][0], colores_botones[0][1], lambda: on_select_mode("chat_soporte")),
        boton_modo(texto_biblia[0], texto_biblia[1], ft.Icons.AUTO_STORIES, colores_botones[1][0], colores_botones[1][1], lambda: on_select_mode("biblia")),
        boton_modo(texto_estudio[0], texto_estudio[1], ft.Icons.FILTER_ALT, colores_botones[2][0], colores_botones[2][1], lambda: on_select_mode("filtros")),
        boton_modo(texto_preguntas[0], texto_preguntas[1], ft.Icons.HELP_OUTLINE, colores_botones[3][0], colores_botones[3][1], lambda: on_select_mode("preguntas")),
        boton_modo(texto_chat_consejero[0], texto_chat_consejero[1], ft.Icons.CHAT, colores_botones[4][0], colores_botones[4][1], lambda: on_select_mode("chat_consejero")),
        boton_modo(texto_chat_suenos[0], texto_chat_suenos[1], ft.Icons.AUTO_AWESOME, colores_botones[5][0], colores_botones[5][1], lambda: on_select_mode("chat_suenos")),
        boton_modo(texto_dones[0], texto_dones[1], ft.Icons.CHECKLIST, colores_botones[6][0], colores_botones[6][1], lambda: on_select_mode("dones")),
    ]

    if on_volver is not None:
        controles.append(
            ft.OutlinedButton(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.ARROW_BACK, size=18, color=theme["text"]),
                        ft.Text(textos["back"], weight="bold", color=theme["text"]),
                    ],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.CENTER,
                    tight=True,
                ),
                on_click=lambda e: on_volver(),
                style=ft.ButtonStyle(
                    side=ft.BorderSide(3, theme["border"]),
                    shape=ft.RoundedRectangleBorder(radius=14),
                    padding=_padding_symmetric(horizontal=16, vertical=10),
                ),
                width=286,
                height=52,
            )
        )

    return ft.Column(
        controls=controles,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=12,
        tight=True,
    )


def pantalla_intro_dones(page: ft.Page, language_code: str, on_continuar, on_volver=None):
    theme = get_language_theme(language_code)
    textos_por_idioma = {
        "es": {
            "title": "ANTES DE HACER EL TEST",
            "subtitle": "Lee primero esta recomendación breve para usar bien el resultado.",
            "recommendation_title": "Recomendación para que el test sea útil:",
            "recommendation_paragraphs": [
                'Para que los resultados sean lo más reales posibles, trata de responder pensando en lo que realmente haces o sientes, no en lo que "crees que deberías ser". Por ejemplo, si te preguntan si te gusta hablar en público, responde con total sinceridad aunque creas que ser "maestro" suena mejor que ser "ayudador". Todos los dones son igual de importantes.',
            ],
            "advice_title": 'Un pequeño consejo de "amigo experto"',
            "advice_intro": "Ningún test es infalible ni una verdad absoluta. Es una herramienta de orientación. La mejor forma de confirmar un don es:",
            "advice_points": [
                "La práctica: intenta servir en diferentes áreas y observa dónde hay fruto.",
                "La confirmación de la comunidad: a menudo otros ven en nosotros talentos que nosotros mismos no notamos.",
                "La oración: busca dirección personal delante de Dios con calma y humildad.",
            ],
            "closing": "Si después del test sigues con dudas, lo mejor es hablarlo con tu pastor o con alguien maduro en la fe.",
            "start": "EMPEZAR TEST",
            "back": "VOLVER",
        },
        "ca": {
            "title": "ABANS DE FER EL TEST",
            "subtitle": "Llegeix primer aquesta recomanacio breu per interpretar millor el resultat.",
            "recommendation_title": "Recomanacio",
            "recommendation_items": [
                '"Test de dons espirituals PDF" si prefereixes imprimir-lo i fer-lo a ma.',
                '"Questionari de carismes cristians online" si vols comparar amb altres eines.',
                "Pagines de recursos eclesials, perque molts ministeris ofereixen versions digitals interactives.",
            ],
            "advice_title": 'Un petit consell de "l amic expert"',
            "advice_intro": "Cap test es infallible ni una veritat absoluta. Es una eina d'orientacio. La millor manera de confirmar un do es:",
            "advice_points": [
                "La practica: intenta servir en diferents arees i observa on hi ha fruit.",
                "La confirmacio de la comunitat: sovint altres veuen en nosaltres talents que nosaltres mateixos no detectem.",
                "La pregaria: busca direccio personal davant de Deu amb calma i humilitat.",
            ],
            "closing": "Si despres del test encara tens dubtes, el millor es parlar-ne amb el teu pastor o amb algu madur en la fe.",
            "start": "COMENCAR TEST",
            "back": "TORNAR",
        },
        "fr": {
            "title": "AVANT LE TEST",
            "subtitle": "Lis d'abord cette breve recommandation pour bien interpreter le resultat.",
            "recommendation_title": "Recommandation",
            "recommendation_items": [
                '"Test des dons spirituels PDF" si tu preferes l imprimer et le faire a la main.',
                '"Questionnaire des charismes chretiens en ligne" si tu veux comparer avec d autres outils.',
                "Pages de ressources d eglise, car beaucoup de ministeres proposent des versions numeriques interactives.",
            ],
            "advice_title": 'Un petit conseil "ami expert"',
            "advice_intro": "Aucun test n est infaillible ni une verite absolue. C est un outil d orientation. La meilleure facon de confirmer un don est :",
            "advice_points": [
                "La pratique : sers dans plusieurs domaines et observe ou il y a du fruit.",
                "La confirmation de la communaute : bien souvent, d autres voient en nous des talents que nous ne remarquons pas.",
                "La priere : cherche la direction de Dieu avec calme et humilite.",
            ],
            "closing": "Si tu restes dans le doute apres le test, le mieux est d en parler avec ton pasteur ou une personne mature dans la foi.",
            "start": "COMMENCER LE TEST",
            "back": "RETOUR",
        },
        "en": {
            "title": "BEFORE THE TEST",
            "subtitle": "Read this short recommendation first so the result helps you in the right way.",
            "recommendation_title": "Recommendation",
            "recommendation_items": [
                '"Spiritual gifts test PDF" if you prefer to print it and work through it by hand.',
                '"Online Christian gifts questionnaire" if you want to compare with other tools.',
                "Church resource pages, since many ministries offer interactive digital versions.",
            ],
            "advice_title": 'A small "trusted friend" note',
            "advice_intro": "No test is infallible or an absolute truth. It is a guidance tool. The best way to confirm a gift is:",
            "advice_points": [
                "Practice: serve in different areas and notice where there is fruit.",
                "Community confirmation: other people often see gifts in us that we do not notice ourselves.",
                "Prayer: seek personal direction from God with calm and humility.",
            ],
            "closing": "If you still have doubts after the test, it is wise to talk with your pastor or a mature believer.",
            "start": "START TEST",
            "back": "BACK",
        },
    }
    textos = textos_por_idioma.get(language_code, textos_por_idioma["es"])

    recomendacion_controles = [
        ft.Text(textos["recommendation_title"], size=18, weight="bold", color=theme["primary"]),
    ]
    if textos.get("recommendation_paragraphs"):
        for parrafo in textos["recommendation_paragraphs"]:
            recomendacion_controles.append(
                ft.Text(parrafo, color=theme["text"], size=14)
            )
    else:
        for item in textos["recommendation_items"]:
            recomendacion_controles.append(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.CHECK_CIRCLE, color=theme["primary"], size=18),
                        ft.Text(item, color=theme["text"], size=13, expand=True),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
            )

    consejo_controles = []
    if textos.get("advice_title"):
        consejo_controles.extend(
            [
                ft.Text(textos["advice_title"], size=20, weight="bold", color=theme["primary"]),
                ft.Text(textos["advice_intro"], color=theme["text"], size=14),
            ]
        )
    for indice, item in enumerate(textos["advice_points"], start=1):
        consejo_controles.append(
            ft.Row(
                [
                    ft.Container(
                        content=ft.Text(str(indice), weight="bold", color=theme["primary_text"]),
                        width=30,
                        height=30,
                        alignment=ft.Alignment(0, 0),
                        bgcolor=theme["primary"],
                        border_radius=15,
                    ),
                    ft.Text(item, color=theme["text"], size=14, expand=True),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )
    if textos.get("closing"):
        consejo_controles.append(
            ft.Text(textos["closing"], color=theme["text"], size=14, weight="bold")
        )

    botones = [
        ft.ElevatedButton(
            textos["start"],
            on_click=lambda e: on_continuar(),
            style=ft.ButtonStyle(
                bgcolor=theme["primary"],
                color=theme["primary_text"],
                side=ft.BorderSide(4, theme["border"]),
                shape=ft.RoundedRectangleBorder(radius=16),
                padding=_padding_symmetric(horizontal=20, vertical=14),
            ),
            width=280,
            height=56,
        )
    ]
    if on_volver is not None:
        botones.append(
            ft.OutlinedButton(
                textos["back"],
                on_click=lambda e: on_volver(),
                style=ft.ButtonStyle(
                    side=ft.BorderSide(3, theme["border"]),
                    color=theme["text"],
                    shape=ft.RoundedRectangleBorder(radius=16),
                    padding=_padding_symmetric(horizontal=20, vertical=14),
                ),
                width=280,
                height=52,
            )
        )

    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.AUTO_AWESOME, size=42, color=theme["primary"]),
                ft.Text(textos["title"], size=24, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER),
                ft.Text(textos["subtitle"], size=14, color=theme["text"], text_align=ft.TextAlign.CENTER),
                ft.Container(
                    padding=16,
                    bgcolor=theme["accent"],
                    border=_border_all(4, theme["panel_border"]),
                    border_radius=20,
                    content=ft.Column(recomendacion_controles, spacing=12),
                ),
                ft.Container(
                    padding=16,
                    bgcolor=theme["panel_bg"],
                    border=_border_all(4, theme["panel_border"]),
                    border_radius=20,
                    content=ft.Column(
                        consejo_controles,
                        spacing=14,
                    ),
                    visible=bool(consejo_controles),
                ),
                ft.Column(
                    botones,
                    spacing=10,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=16,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.AUTO,
        ),
        width=360,
        padding=18,
        border_radius=24,
        bgcolor=theme["panel_bg"],
        border=_border_all(6, theme["primary"]),
        shadow=ft.BoxShadow(blur_radius=18, color="#0000001A", offset=ft.Offset(0, 6)),
    )


def pantalla_intro_suenos(page: ft.Page, language_code: str, on_continuar, on_volver=None):
    theme = get_language_theme(language_code)
    textos_por_idioma = {
        "es": {
            "title": "ANTES DE INTERPRETAR UN SUEÑO",
            "subtitle": "Usa esta sección como ayuda bíblica y pastoral, no como un oráculo.",
            "notice_title": "Consideraciones éticas y doctrinales",
            "notice_paragraphs": [
                "Esta herramienta no reemplaza la Biblia, la oración ni la guía de un pastor. La interpretación final no la decide una app, sino Dios en su verdad y su voluntad.",
                "No trabajamos con astrología, tarot, numerología, energías, amuletos ni lenguaje esotérico. Si un símbolo no tiene base bíblica suficiente, lo más honesto será decirlo con claridad.",
            ],
            "how_title": "Cómo funciona",
            "how_intro": "La orientación del chat se apoya en tres pilares:",
            "how_points": [
                "Base bíblica: cada observación debe anclarse en las Escrituras, no en diccionarios místicos.",
                "Simbología cristiana: los símbolos solo se interpretan según su contexto bíblico y el contexto del sueño.",
                "Discernimiento espiritual: no todo sueño tiene un mensaje especial; a veces refleja cargas, temores o recuerdos.",
            ],
            "use_title": "Qué conviene contar en el chat",
            "use_points": [
                "Describe el sueño con los detalles principales: personas, lugares, acciones y emociones.",
                "Cuenta también tu contexto actual: qué estás viviendo, orando o discerniendo en estos días.",
                "Recibirás una respuesta prudente, del tipo 'esto podría sugerir...', no afirmaciones absolutas sobre el futuro.",
            ],
            "closing": "Si un sueño te inquieta mucho o crees que tiene peso espiritual, lo mejor es orarlo y comentarlo con tu pastor o con creyentes maduros.",
            "start": "ABRIR CHAT DE SUEÑOS",
            "back": "VOLVER",
        },
        "ca": {
            "title": "ABANS D'INTERPRETAR UN SOMNI",
            "subtitle": "Fes servir aquesta secció com a ajuda bíblica i pastoral, no com un oracle.",
            "notice_title": "Consideracions ètiques i doctrinals",
            "notice_paragraphs": [
                "Aquesta eina no substitueix la Bíblia, la pregària ni la guia d'un pastor. La interpretació final no la decideix una app, sinó Déu en la seva veritat i voluntat.",
                "No treballem amb astrologia, tarot, numerologia, energies, amulets ni llenguatge esotèric. Si un símbol no té prou base bíblica, el més honest serà dir-ho clarament.",
            ],
            "how_title": "Com funciona",
            "how_intro": "L'orientació del xat es recolza en tres pilars:",
            "how_points": [
                "Base bíblica: cada observació s'ha d'ancorar a les Escriptures, no a diccionaris místics.",
                "Simbologia cristiana: els símbols només s'interpreten segons el seu context bíblic i el context del somni.",
                "Discerniment espiritual: no tot somni té un missatge especial; de vegades reflecteix càrregues, pors o records.",
            ],
            "use_title": "Què convé explicar al xat",
            "use_points": [
                "Descriu el somni amb els detalls principals: persones, llocs, accions i emocions.",
                "Explica també el teu context actual: què estàs vivint, pregant o discernint aquests dies.",
                "Rebràs una resposta prudent, del tipus 'això podria suggerir...', no afirmacions absolutes sobre el futur.",
            ],
            "closing": "Si un somni t'inquieta molt o creus que té pes espiritual, el millor és pregar-ho i comentar-ho amb el teu pastor o amb creients madurs.",
            "start": "OBRIR XAT DE SOMNIS",
            "back": "TORNAR",
        },
        "fr": {
            "title": "AVANT D'INTERPRÉTER UN RÊVE",
            "subtitle": "Utilise cette section comme une aide biblique et pastorale, pas comme un oracle.",
            "notice_title": "Considérations éthiques et doctrinales",
            "notice_paragraphs": [
                "Cet outil ne remplace ni la Bible, ni la prière, ni la direction d'un pasteur. L'interprétation finale n'appartient pas à une application mais à Dieu, dans sa vérité et sa volonté.",
                "Nous n'utilisons ni astrologie, ni tarot, ni numérologie, ni énergies, ni langage ésotérique. Si un symbole n'a pas de base biblique suffisante, le plus honnête sera de le dire clairement.",
            ],
            "how_title": "Comment cela fonctionne",
            "how_intro": "L'orientation du chat repose sur trois piliers :",
            "how_points": [
                "Base biblique : chaque observation doit être ancrée dans l'Écriture, non dans des dictionnaires mystiques.",
                "Symbolique chrétienne : les symboles ne s'interprètent qu'à la lumière de leur contexte biblique et du contexte du rêve.",
                "Discernement spirituel : tous les rêves ne portent pas un message spécial ; certains reflètent simplement des charges, des peurs ou des souvenirs.",
            ],
            "use_title": "Que raconter dans le chat",
            "use_points": [
                "Décris le rêve avec les détails principaux : personnes, lieux, actions et émotions.",
                "Ajoute aussi ton contexte actuel : ce que tu vis, ce pour quoi tu pries, ce que tu discernes en ce moment.",
                "Tu recevras une réponse prudente du type 'cela pourrait suggérer...', et non des affirmations absolues sur l'avenir.",
            ],
            "closing": "Si un rêve t'inquiète beaucoup ou te semble spirituellement important, le mieux est de le remettre dans la prière et d'en parler avec ton pasteur ou avec des croyants mûrs.",
            "start": "OUVRIR LE CHAT DES RÊVES",
            "back": "RETOUR",
        },
        "en": {
            "title": "BEFORE INTERPRETING A DREAM",
            "subtitle": "Use this section as biblical and pastoral help, not as an oracle.",
            "notice_title": "Ethical and doctrinal considerations",
            "notice_paragraphs": [
                "This tool does not replace the Bible, prayer, or the guidance of a pastor. Final interpretation does not belong to an app, but to God in his truth and will.",
                "We do not work with astrology, tarot, numerology, energies, charms, or esoteric language. If a symbol does not have enough biblical basis, the most honest answer is to say so clearly.",
            ],
            "how_title": "How it works",
            "how_intro": "The chat relies on three pillars:",
            "how_points": [
                "Biblical foundation: every observation must be anchored in Scripture, not in mystical dream dictionaries.",
                "Christian symbolism: symbols are interpreted only through their biblical context and the context of the dream.",
                "Spiritual discernment: not every dream carries a special message; some simply reflect burdens, fears, or memories.",
            ],
            "use_title": "What to share in the chat",
            "use_points": [
                "Describe the dream with the main details: people, places, actions, and emotions.",
                "Also share your current context: what you are living through, praying about, or discerning these days.",
                "You will receive a careful response such as 'this could suggest...', not absolute claims about the future.",
            ],
            "closing": "If a dream troubles you deeply or seems spiritually weighty, the wisest step is to pray about it and talk with your pastor or mature believers.",
            "start": "OPEN DREAM CHAT",
            "back": "BACK",
        },
    }
    textos = textos_por_idioma.get(language_code, textos_por_idioma["es"])

    aviso_controles = [
        ft.Text(textos["notice_title"], size=18, weight="bold", color=theme["primary"]),
    ]
    for parrafo in textos["notice_paragraphs"]:
        aviso_controles.append(ft.Text(parrafo, color=theme["text"], size=14))

    base_controles = [
        ft.Text(textos["how_title"], size=20, weight="bold", color=theme["primary"]),
        ft.Text(textos["how_intro"], color=theme["text"], size=14),
    ]
    for indice, item in enumerate(textos["how_points"], start=1):
        base_controles.append(
            ft.Row(
                [
                    ft.Container(
                        content=ft.Text(str(indice), weight="bold", color=theme["primary_text"]),
                        width=30,
                        height=30,
                        alignment=ft.Alignment(0, 0),
                        bgcolor=theme["primary"],
                        border_radius=15,
                    ),
                    ft.Text(item, color=theme["text"], size=14, expand=True),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )

    uso_controles = [
        ft.Text(textos["use_title"], size=20, weight="bold", color=theme["primary"]),
    ]
    for item in textos["use_points"]:
        uso_controles.append(
            ft.Row(
                [
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=theme["primary"], size=18),
                    ft.Text(item, color=theme["text"], size=14, expand=True),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )
    uso_controles.append(ft.Text(textos["closing"], color=theme["text"], size=14, weight="bold"))

    botones = [
        ft.ElevatedButton(
            textos["start"],
            on_click=lambda e: on_continuar(),
            style=ft.ButtonStyle(
                bgcolor=theme["primary"],
                color=theme["primary_text"],
                side=ft.BorderSide(4, theme["border"]),
                shape=ft.RoundedRectangleBorder(radius=16),
                padding=_padding_symmetric(horizontal=20, vertical=14),
            ),
            width=280,
            height=56,
        )
    ]
    if on_volver is not None:
        botones.append(
            ft.OutlinedButton(
                textos["back"],
                on_click=lambda e: on_volver(),
                style=ft.ButtonStyle(
                    side=ft.BorderSide(3, theme["border"]),
                    color=theme["text"],
                    shape=ft.RoundedRectangleBorder(radius=16),
                    padding=_padding_symmetric(horizontal=20, vertical=14),
                ),
                width=280,
                height=52,
            )
        )

    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.AUTO_AWESOME, size=42, color=theme["primary"]),
                ft.Text(textos["title"], size=24, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER),
                ft.Text(textos["subtitle"], size=14, color=theme["text"], text_align=ft.TextAlign.CENTER),
                ft.Container(
                    padding=16,
                    bgcolor=theme["accent"],
                    border=_border_all(4, theme["panel_border"]),
                    border_radius=20,
                    content=ft.Column(aviso_controles, spacing=12),
                ),
                ft.Container(
                    padding=16,
                    bgcolor=theme["panel_bg"],
                    border=_border_all(4, theme["panel_border"]),
                    border_radius=20,
                    content=ft.Column(base_controles, spacing=14),
                ),
                ft.Container(
                    padding=16,
                    bgcolor=theme["panel_bg"],
                    border=_border_all(4, theme["panel_border"]),
                    border_radius=20,
                    content=ft.Column(uso_controles, spacing=12),
                ),
                ft.Column(
                    botones,
                    spacing=10,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=16,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.AUTO,
        ),
        width=360,
        padding=18,
        border_radius=24,
        bgcolor=theme["panel_bg"],
        border=_border_all(6, theme["primary"]),
        shadow=ft.BoxShadow(blur_radius=18, color="#0000001A", offset=ft.Offset(0, 6)),
    )


def pantalla_selector_preguntas(page: ft.Page, language_code: str, on_select_mode, on_volver=None):
    cfg = get_language_config(language_code)
    theme = get_language_theme(language_code)
    titulo = {
        "es": "PREGUNTAS",
        "ca": "PREGUNTES",
        "fr": "QUESTIONS",
        "en": "QUESTIONS",
    }.get(language_code, "PREGUNTAS")
    subtitulo = {
        "es": "Elige una de estas tres opciones",
        "ca": "Tria una d'aquestes tres opcions",
        "fr": "Choisis l'une de ces trois options",
        "en": "Choose one of these three options",
    }.get(language_code, "Elige una de estas tres opciones")
    texto_comportamiento = {
        "es": ("CÓMO COMPORTARME SI...", "CRÍTICAS, ENFADOS, CONFLICTOS, ETC"),
        "ca": ("COM COMPORTAR-ME SI...", "CRÍTIQUES, ENFADAMENTS, CONFLICTES, ETC"),
        "fr": ("COMMENT ME COMPORTER SI...", "CRITIQUES, COLÈRES, CONFLITS, ETC"),
        "en": ("HOW SHOULD I RESPOND IF...", "CRITICISM, ANGER, CONFLICTS, ETC"),
    }.get(language_code, ("CÓMO COMPORTARME SI...", "CRÍTICAS, ENFADOS, CONFLICTOS, ETC"))
    texto_incredulo = {
        "es": ("QUÉ RESPONDER A UN INCRÉDULO SI...", "PREGUNTAS DIFÍCILES, FE, BIBLIA, DIOS, ETC"),
        "ca": ("QUÈ RESPONDRE A UN INCRÈDUL SI...", "PREGUNTES DIFÍCILS, FE, BÍBLIA, DÉU, ETC"),
        "fr": ("QUE RÉPONDRE À UN INCRÉDULE SI...", "QUESTIONS DIFFICILES, FOI, BIBLE, DIEU, ETC"),
        "en": ("WHAT TO ANSWER AN UNBELIEVER IF...", "HARD QUESTIONS, FAITH, BIBLE, GOD, ETC"),
    }.get(language_code, ("QUÉ RESPONDER A UN INCRÉDULO SI...", "PREGUNTAS DIFÍCILES, FE, BIBLIA, DIOS, ETC"))
    texto_cristianos = {
        "es": ("PREGUNTAS QUE LOS CRISTIANOS NOS HACEMOS", "DUDAS DE FE, ORACIÓN, PRUEBAS, GUÍA DE DIOS, ETC"),
        "ca": ("PREGUNTES QUE ELS CRISTIANS ENS FEM", "DUBTES DE FE, ORACIÓ, PROVES, GUIA DE DÉU, ETC"),
        "fr": ("QUESTIONS QUE LES CHRÉTIENS SE POSENT", "DOUTES, PRIÈRE, ÉPREUVES, DIRECTION DE DIEU, ETC"),
        "en": ("QUESTIONS CHRISTIANS ASK", "FAITH DOUBTS, PRAYER, TRIALS, GOD'S GUIDANCE, ETC"),
    }.get(language_code, ("PREGUNTAS QUE LOS CRISTIANOS NOS HACEMOS", "DUDAS DE FE, ORACIÓN, PRUEBAS, GUÍA DE DIOS, ETC"))
    texto_volver = {
        "es": "VOLVER",
        "ca": "TORNAR",
        "fr": "RETOUR",
        "en": "BACK",
    }.get(language_code, "VOLVER")
    colores_botones = {
        "es": [
            ("#C60B1E", "#FFFFFF"),
            ("#FFC400", "#2F1B00"),
            ("#C60B1E", "#FFFFFF"),
        ],
        "ca": [
            ("#C8102E", "#FFFFFF"),
            ("#F6D04D", "#351600"),
            ("#C8102E", "#FFFFFF"),
        ],
        "fr": [
            ("#EF4135", "#FFFFFF"),
            ("#0055A4", "#FFFFFF"),
            ("#0055A4", "#FFFFFF"),
        ],
        "en": [
            ("#C8102E", "#FFFFFF"),
            ("#012169", "#FFFFFF"),
            ("#012169", "#FFFFFF"),
        ],
    }.get(language_code, [
        (theme["primary"], theme["primary_text"]),
        (theme["secondary"], theme["secondary_text"]),
        (theme["primary"], theme["primary_text"]),
    ])

    def boton_modo(texto, ayuda, icono, color_fondo, color_texto, accion):
        contenido = [
            ft.Icon(icono, size=28, color=color_texto),
            ft.Text(texto, size=16, weight="bold", color=color_texto, text_align=ft.TextAlign.CENTER),
        ]
        if ayuda:
            contenido.append(ft.Text(ayuda, size=11, color=color_texto, text_align=ft.TextAlign.CENTER))
        return ft.ElevatedButton(
            content=ft.Column(
                contenido,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=5,
                tight=True,
            ),
            on_click=lambda e: accion(),
            style=ft.ButtonStyle(
                bgcolor=color_fondo,
                color=color_texto,
                side=ft.BorderSide(4, theme["border"]),
                shape=ft.RoundedRectangleBorder(radius=16),
                padding=10,
            ),
            width=286,
            height=92,
        )

    controles = [
        ft.Icon(ft.Icons.HELP_OUTLINE, color=theme["primary"], size=44),
        ft.Text(cfg["welcome"]["title"], size=24, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER),
        ft.Text(titulo, size=20, weight="bold", color=theme["text"], text_align=ft.TextAlign.CENTER),
        ft.Text(subtitulo, size=13, color=theme["text"], text_align=ft.TextAlign.CENTER),
        ft.Divider(height=4, color="transparent"),
        boton_modo(texto_comportamiento[0], None, ft.Icons.FORUM, colores_botones[0][0], colores_botones[0][1], lambda: on_select_mode("comportamiento")),
        boton_modo(texto_incredulo[0], None, ft.Icons.RECORD_VOICE_OVER, colores_botones[1][0], colores_botones[1][1], lambda: on_select_mode("incredulo")),
        boton_modo(texto_cristianos[0], None, ft.Icons.HELP_OUTLINE, colores_botones[2][0], colores_botones[2][1], lambda: on_select_mode("cristianos")),
    ]

    if on_volver is not None:
        controles.append(
            ft.OutlinedButton(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.ARROW_BACK, size=18, color=theme["text"]),
                        ft.Text(texto_volver, weight="bold", color=theme["text"]),
                    ],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.CENTER,
                    tight=True,
                ),
                on_click=lambda e: on_volver(),
                style=ft.ButtonStyle(
                    side=ft.BorderSide(3, theme["border"]),
                    shape=ft.RoundedRectangleBorder(radius=14),
                    padding=_padding_symmetric(horizontal=16, vertical=10),
                ),
                width=286,
                height=52,
            )
        )

    return ft.Column(
        controls=controles,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=12,
        tight=True,
    )


def pantalla_carga_saludo(page: ft.Page, language_code: str):
    cfg = get_language_config(language_code)
    theme = get_language_theme(language_code)
    welcome = cfg["welcome"]
    saludo_mostrar = _obtener_siguiente_saludo(language_code)
    aviso_actualizacion = ft.Container(
        content=ft.Text(
            welcome["update_notice"],
            size=18,
            color=theme["text"],
            text_align=ft.TextAlign.CENTER,
        ),
        padding=20,
        bgcolor=theme["accent"],
        border=_border_all(4, theme["panel_border"]),
        border_radius=16,
        width=360,
    )

    return ft.Column(
        controls=[
            ft.ProgressRing(width=56, height=56, stroke_width=6, color=theme["primary"]),
            ft.Text(welcome["title"], size=28, weight="bold", color=theme["primary"], text_align=ft.TextAlign.CENTER),
            ft.Row(
                [
                    _crear_bandera(cfg["flag"]),
                    ft.Text(cfg["native_name"], size=18, weight="bold", color=theme["text"]),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=10,
            ),
            ft.Container(
                content=ft.Text(
                    saludo_mostrar,
                    size=18,
                    color=theme["text"],
                    text_align=ft.TextAlign.CENTER,
                ),
                padding=20,
                bgcolor=theme["field_bg"],
                border=_border_all(4, theme["panel_border"]),
                border_radius=16,
                width=360,
            ),
            aviso_actualizacion,
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=22,
        tight=True,
    )


