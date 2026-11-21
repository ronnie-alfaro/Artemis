from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.models import (
    Agent,
    AgentCapability,
    AgentRequest,
    AgentResponse,
    AgentResult,
    IncomingMessage,
    Permission,
)
from app.domain.skills import TMDB_CAPABILITY
from app.infrastructure.tmdb import TmdbClient, TmdbError

Media = Literal["movie", "tv", "both"]
GENRES = {
    "terror": (27, None), "horror": (27, None), "comedia": (35, 35),
    "drama": (18, 18), "animacion": (16, 16), "documental": (99, 99),
    "crimen": (80, 80), "misterio": (9648, 9648), "accion": (28, 10759),
    "ciencia ficcion": (878, 10765), "fantasia": (14, 10765),
    "thriller": (53, None), "suspenso": (53, None), "aventura": (12, 10759),
    "romance": (10749, None), "familia": (10751, 10751),
}
HELP = (
    "Catálogo TMDB de solo lectura. En conversación natural traduce la petición a un objeto "
    "JSON con action (search, details, next_episode, recommendations, similar, compare, "
    "trending, upcoming, discover, keyword, airing, providers), media (movie, tv, both), "
    "query (título o keyword), second_query y second_media para compare, year, genre (nombre "
    "en español o ID), keyword (nombre o ID para filtrar discover), start_date/end_date (ISO), "
    "region (ISO de dos letras), language, window (day/week), "
    "sort (popular/rating/newest/soonest), min_votes, page y limit. "
    "Para un título ya identificado, usa media y tmdb_id. "
    "Traduce palabras clave al inglés para buscarlas en TMDB. "
    "Conserva los enlaces de póster y la atribución de TMDB en la respuesta. "
    "Si el usuario pide guardar un resultado en la watchlist de Seerr, reutiliza su tipo e ID "
    'TMDB en seerr.media con seerr api POST /api/v1/watchlist {"tmdbId":123,"mediaType":"movie"} '
    "(sustituye ambos valores por los reales), y pide la confirmación de Seerr. "
    "Ejemplos directos: «tendencias de series», «qué películas de horror vienen», "
    "«mejores películas de terror de 2019», «próximo capítulo de Severance», "
    "«similares a Alien», «compara Alien con Aliens», «keyword viajes en el tiempo»."
)


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal[
        "search", "details", "next_episode", "recommendations", "similar", "compare",
        "trending", "upcoming", "discover", "keyword", "airing", "providers",
    ]
    media: Media = "both"
    query: str = Field(default="", max_length=200)
    second_query: str = Field(default="", max_length=200)
    second_media: Media | None = None
    tmdb_id: int | None = Field(default=None, gt=0)
    year: int | None = Field(default=None, ge=1870, le=2200)
    genre: str | int | None = None
    keyword: str | int | None = None
    start_date: date | None = None
    end_date: date | None = None
    region: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    language: str = Field(default="es", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    window: Literal["day", "week"] = "week"
    sort: Literal["popular", "rating", "newest", "soonest"] = "popular"
    min_votes: int | None = Field(default=None, ge=0)
    page: int = Field(default=1, ge=1, le=500)
    limit: int = Field(default=5, ge=1, le=10)


def normalize(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", value.casefold())
        if not unicodedata.combining(char)
    )


def natural_query(content: str, *, explicit: bool = False) -> Query | None:
    original = content.strip(" ¿?¡!").rstrip(".")
    words = normalize(original)
    media: Media = (
        "tv" if re.search(r"\b(series?|tv|shows?)\b", words)
        else "movie" if re.search(r"\b(pelis?|peliculas?)\b", words) else "both"
    )
    options: dict[str, Any] = {"media": media}
    region = re.search(r"\s+en ([A-Z]{2})$", original)
    if region:
        options["region"] = region[1]
    year = re.search(r"\b(18[7-9]\d|19\d{2}|20\d{2}|21\d{2}|2200)\b", words)
    genre = next((name for name in GENRES if re.search(rf"\b{name}\b", words)), None)
    if re.search(r"\btendencias?\b", words) or words.startswith("trending"):
        window: Literal["day", "week"] = (
            "day" if re.search(r"\b(hoy|dia|day)\b", words) else "week"
        )
        return Query(action="trending", window=window, **options)
    if (media != "both" or explicit or "estreno" in words) and re.search(
        r"\b(estrenos?|vienen?|proxim[oa]s? (peliculas|series|estrenos))\b", words,
    ):
        return Query(action="upcoming", genre=genre, year=int(year[1]) if year else None,
                     **options)
    if words.startswith(("mejores ", "top ", "cuales son las mejores ")) and (
        media != "both" or explicit or genre
    ):
        return Query(action="discover", sort="rating", genre=genre,
                     year=int(year[1]) if year else None, **options)
    if words.startswith(("series en emision", "series hoy", "que series dan hoy")):
        return Query(action="airing", media="tv", window="day" if "hoy" in words else "week")
    patterns = {
        "next_episode": (
            r"(?:.*?\b)?(?:proxim[oa]|nuev[oa]) (?:capitulo|episodio) (?:de |en )?"
            r"(?:(?:la )?serie )?(.+)"
            r"|.*?\b(?:capitulo|episodio) (?:nuevo|proximo) (?:de |en )?"
            r"(?:(?:la )?serie )?(.+)"
        ),
        "similar": r"(?:.*?\b)?(?:similares?|parecid[oa]s?) a (.+)",
        "recommendations": r"(?:si me gusta|recomendaciones (?:para|de)|recomienda como) (.+)",
        "keyword": r"(?:.*?\b)?(?:keyword|palabra clave)\s*[:=]?\s+(.+)",
        "providers": r"donde (?:ver|puedo ver) (.+)",
        "details": r"(?:ficha|detalles|hablame|informacion) (?:de |sobre )?(.+)",
        "search": r"(?:busca|buscar|buscame) (?:la |el )?(.+)",
    }
    compare = re.fullmatch(r"compara(?:r)? (.+?) (?:con|y|vs\.?) (.+)", words)
    if compare:
        return Query(action="compare", query=original[slice(*compare.span(1))],
                     second_query=original[slice(*compare.span(2))], **options)
    for action, pattern in patterns.items():
        match = re.fullmatch(pattern, words)
        if match and (action != "search" or explicit or media != "both"):
            group = next(index for index, value in enumerate(match.groups(), 1) if value)
            title = original[slice(*match.span(group))]
            if action in {"search", "details", "providers", "similar", "recommendations"}:
                title = re.sub(
                    r"^(?:la |el )?(?:pel[ií]cula|peli|serie|show)\s+", "", title,
                    flags=re.IGNORECASE,
                )
            if action == "recommendations":
                title = title.split(",", 1)[0]
            if action != "keyword":
                if region and title.endswith(region[0]):
                    title = title[:-len(region[0])]
                title_year = re.fullmatch(r"(.+?)\s+(?:de |\()?((?:18|19|20|21)\d{2})\)?", title)
                if title_year and 1870 <= int(title_year[2]) <= 2200:
                    title, options["year"] = title_year[1], int(title_year[2])
            if action == "next_episode":
                options["media"] = "tv"
            return Query.model_validate({"action": action, "query": title, **options})
    if explicit and original:
        return Query(action="search", query=original, **options)
    return None


class TmdbAgent:
    definition = Agent(
        name="tmdb", version="0.1.0", timeout_seconds=40,
        purpose="Consulta películas, series, estrenos y episodios en The Movie Database.",
        capabilities=[AgentCapability(
            name=TMDB_CAPABILITY, description="Busca y compara películas y series en TMDB",
            help_text=HELP,
        )],
        permissions=[Permission(name="tmdb.catalog.read", description="Consulta TMDB")],
    )

    def __init__(self, client: TmdbClient) -> None:
        self._client = client

    def select(self, message: IncomingMessage) -> str | None:
        if message.channel.allowed_capabilities and TMDB_CAPABILITY not in (
            message.channel.allowed_capabilities
        ):
            return None
        text = message.content.strip()
        if re.match(r"^/?tmdb\b", text, re.IGNORECASE):
            return TMDB_CAPABILITY
        if not self._client.configured or re.search(
            r"\b(?:seerr|watchlist|solicitar|quiero pedir)\b", normalize(text)
        ):
            return None
        try:
            return TMDB_CAPABILITY if natural_query(text) else None
        except ValidationError:
            return None

    async def run(self, request: AgentRequest) -> AgentResponse:
        command = re.sub(r"^/?tmdb\b\s*", "", request.message.content.strip(), flags=re.I)
        try:
            query = (
                Query.model_validate_json(command) if command.startswith("{")
                else natural_query(command, explicit=True)
            )
            content = await self.execute(query) if query else HELP
        except ValidationError:
            content = "Consulta TMDB inválida. Escribe «ayuda TMDB» para ver ejemplos."
        except TmdbError as error:
            content = str(error)
        return AgentResponse(result=AgentResult(
            agent_name="tmdb",
            content=content,
            metadata={"execution_id": str(request.execution_id)},
        ))

    async def execute(self, query: Query) -> str:
        params: dict[str, str | int | float] = {"language": query.language, "page": query.page}
        kinds = ("movie", "tv") if query.media == "both" else (query.media,)
        action = query.action
        if action == "trending":
            groups = await asyncio.gather(*(
                self._client.get(f"trending/{kind}/{query.window}", **params) for kind in kinds
            ))
            return render_groups("Tendencias de hoy" if query.window == "day" else
                                 "Tendencias de la semana", kinds, groups, query.limit)
        if action in {"discover", "keyword", "upcoming", "airing"}:
            return await self._browse(query, kinds)
        if action == "search":
            items = await self._search(query, query.query, query.media, query.year)
            return render_list("Resultados de TMDB", items, query.limit)
        media = "tv" if action == "next_episode" else query.media
        if query.tmdb_id and media == "both":
            raise TmdbError("Indica si el ID de TMDB corresponde a una película o una serie.")
        first = await self._resolve(query, query.query, media, query.tmdb_id)
        if action == "compare":
            second = await self._resolve(
                query.model_copy(update={"year": None}),
                query.second_query, query.second_media or media, None,
            )
            first = dict(first)
            second = dict(second)
            for item in (first, second):
                item["overview"] = (item.get("overview") or "")[:400]
            return render_list("Comparación · nota y votos de TMDB", [first, second], 2)
        kind, tmdb_id = first["media_type"], first["id"]
        if action in {"recommendations", "similar"}:
            result = await self._client.get(f"{kind}/{tmdb_id}/{action}", **params)
            label = "Recomendaciones para" if action == "recommendations" else "Similares a"
            if action == "recommendations" and not result.get("results"):
                result = await self._client.get(f"{kind}/{tmdb_id}/similar", **params)
                label = "Similares a"
            return render_list(f"{label} {title_of(first)}", typed_results(result, kind),
                               query.limit)
        if action == "next_episode":
            return render_episode(first)
        if action == "providers":
            if not query.region:
                raise TmdbError("Indica el país para consultar dónde verlo, por ejemplo «en CR».")
            country = query.region.upper()
            result = await self._client.get(f"{kind}/{tmdb_id}/watch/providers")
            availability = result.get("results", {}).get(country, {})
            labels = {"flatrate": "Suscripción", "free": "Gratis", "ads": "Con anuncios",
                      "rent": "Alquiler", "buy": "Compra"}
            lines = [
                f"{label} · " + ", ".join(p["provider_name"] for p in availability[key])
                for key, label in labels.items() if availability.get(key)
            ]
            return "\n".join([
                f"{title_of(first)} · {country}", *(lines or ["Sin datos de disponibilidad."]),
                availability.get("link", tmdb_link(first)),
                "Datos de TMDB y JustWatch.",
            ])
        return render_list("Ficha de TMDB", [first], 1)

    async def _search(
        self, query: Query, title: str, media: Media, year: int | None,
    ) -> list[dict[str, Any]]:
        if not title:
            raise TmdbError("Indica el título que quieres buscar.")
        kinds = ("movie", "tv") if media == "both" else (media,)
        params: dict[str, str | int | float] = {
            "query": title, "language": query.language, "page": query.page,
            "include_adult": "false",
        }
        groups = await asyncio.gather(*(
            self._client.get(
                f"search/{kind}", **params,
                **({"year" if kind == "movie" else "first_air_date_year": year} if year else {}),
            ) for kind in kinds
        ))
        return sorted(
            (item for kind, group in zip(kinds, groups, strict=True)
             for item in typed_results(group, kind)),
            key=lambda item: (
                normalize(title) in normalized_titles(item),
                item.get("popularity") or 0,
            ),
            reverse=True,
        )

    async def _resolve(
        self, query: Query, title: str, media: Media, tmdb_id: int | None,
    ) -> dict[str, Any]:
        if not tmdb_id:
            candidates = await self._search(query, title, media, query.year)
            if not candidates:
                raise TmdbError(f"No encontré «{title}» en TMDB.")
            exact = [item for item in candidates if normalize(title) in normalized_titles(item)]
            if len(exact) > 1:
                ranked = sorted(exact, key=lambda item: item.get("vote_count") or 0, reverse=True)
                votes = ranked[0].get("vote_count") or 0
                runner_up = ranked[1].get("vote_count") or 0
                if votes < 100 or votes < 10 * runner_up:
                    raise TmdbError(render_list(
                        "Hay varios títulos con ese nombre. Indica año, tipo o ID", exact, 5,
                    ))
                exact = ranked
            match = exact[0] if exact else candidates[0]
            media, tmdb_id = match["media_type"], match["id"]
        details = await self._client.get(f"{media}/{tmdb_id}", language=query.language)
        return {**details, "media_type": media}

    async def _browse(self, query: Query, kinds: tuple[str, ...]) -> str:
        params: dict[str, str | int | float] = {
            "language": query.language, "page": query.page,
            "include_adult": "false",
        }
        today = datetime.now(UTC).date()
        start, end = query.start_date, query.end_date
        if query.year:
            start = start or date(query.year, 1, 1)
            end = end or date(query.year, 12, 31)
        if query.action in {"upcoming", "airing"}:
            start = start or today
            if query.action == "upcoming":
                start = max(start, today)
            days = 90 if query.action == "upcoming" else 0 if query.window == "day" else 6
            end = end or (start + timedelta(days=days))
        if start and end and start > end:
            raise TmdbError("El intervalo solicitado no contiene fechas aplicables.")
        keyword = query.query if query.action == "keyword" else query.keyword
        if query.action == "keyword" and not keyword:
            raise TmdbError("Indica la palabra clave que quieres buscar.")
        if keyword:
            keyword_id, keyword_name = await self._keyword(keyword)
            params["with_keywords"] = keyword_id
        else:
            keyword_name = ""
        tasks = {}
        for kind in kinds:
            variant = dict(params)
            if query.genre:
                genre_id, fallback_keyword = await self._genre(query.genre, kind)
                if genre_id:
                    variant["with_genres"] = genre_id
                if fallback_keyword:
                    previous = variant.get("with_keywords")
                    variant["with_keywords"] = (
                        f"{previous},{fallback_keyword}" if previous else fallback_keyword
                    )
            if query.action == "airing" and kind == "movie":
                continue
            if query.region:
                variant["region" if kind == "movie" else "watch_region"] = query.region.upper()
                if kind == "movie" and query.action == "upcoming":
                    variant["with_release_type"] = "3|2"
            date_field = "primary_release_date" if kind == "movie" else "first_air_date"
            if kind == "movie" and query.region:
                date_field = "release_date"
            if query.action == "airing":
                date_field = "air_date"
                variant["include_null_first_air_dates"] = "false"
            if start:
                variant[f"{date_field}.gte"] = start.isoformat()
            if end:
                variant[f"{date_field}.lte"] = end.isoformat()
            sort_date = "primary_release_date" if kind == "movie" else "first_air_date"
            sort = "soonest" if query.action == "upcoming" and query.sort == "popular" else (
                query.sort
            )
            variant["sort_by"] = {
                "popular": "popularity.desc", "rating": "vote_average.desc",
                "newest": f"{sort_date}.desc", "soonest": f"{sort_date}.asc",
            }[sort]
            votes = query.min_votes if query.min_votes is not None else (
                (100 if kind == "movie" else 25) if sort == "rating" else 0
            )
            if votes:
                variant["vote_count.gte"] = votes
            tasks[kind] = variant
        groups = await asyncio.gather(*(
            self._client.get(f"discover/{kind}", **params) for kind, params in tasks.items()
        ))
        label = {
            "discover": "Mejor valorados" if query.sort == "rating" else "Descubrimiento",
            "keyword": "Resultados por palabra clave",
            "upcoming": "Próximos estrenos",
            "airing": "Series con emisiones programadas",
        }[query.action]
        filters = [str(query.genre or ""), keyword_name,
                   f"{start or '…'} a {end or '…'}" if start or end else ""]
        if query.region and "movie" in tasks:
            filters.append(f"Fechas de películas · {query.region.upper()}")
        return render_groups(
            " · ".join([label, *(value for value in filters if value)]),
            tuple(tasks), groups, query.limit,
        )

    async def _keyword(self, keyword: str | int) -> tuple[int, str]:
        if str(keyword).isdigit() and int(keyword) > 0:
            return int(keyword), f"keyword {keyword}"
        result = await self._client.get("search/keyword", query=str(keyword))
        matches = result.get("results", [])
        if not matches:
            raise TmdbError(f"TMDB no encontró la palabra clave «{keyword}».")
        match = next(
            (item for item in matches if normalize(item["name"]) == normalize(str(keyword))),
            matches[0],
        )
        return int(match["id"]), str(match["name"])

    async def _genre(self, genre: str | int, kind: str) -> tuple[int | None, int | None]:
        if str(genre).isdigit() and int(genre) > 0:
            return int(genre), None
        name = normalize(str(genre))
        if name in GENRES:
            genre_id = GENRES[name][0 if kind == "movie" else 1]
            if genre_id:
                return genre_id, None
            fallback = {"terror": "horror", "suspenso": "thriller"}.get(name, name)
            keyword_id, _ = await self._keyword(fallback)
            return None, keyword_id
        results = await asyncio.gather(*(
            self._client.get(f"genre/{kind}/list", language=language)
            for language in ("es", "en")
        ))
        for result in results:
            for item in result.get("genres", []):
                if normalize(item["name"]) == name:
                    return int(item["id"]), None
        raise TmdbError(f"TMDB no tiene el género «{genre}» para ese tipo de título.")


def typed_results(group: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [{**item, "media_type": kind} for item in group.get("results", [])
            if not item.get("adult")]


def title_of(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("name") or "Sin título")


def display_title(item: dict[str, Any]) -> str:
    title = title_of(item)
    original = item.get("original_title") or item.get("original_name")
    if original and normalize(title) != normalize(original):
        return f"{title} ({original})"
    return title


def normalized_titles(item: dict[str, Any]) -> set[str]:
    return {
        normalize(title_of(item)),
        normalize(item.get("original_title") or item.get("original_name") or ""),
    }


def tmdb_link(item: dict[str, Any]) -> str:
    return f"https://www.themoviedb.org/{item['media_type']}/{item['id']}"


def image_url(path: str | None, size: str = "w342") -> str | None:
    if path and re.fullmatch(r"/[A-Za-z0-9_-]+\.(?:jpg|png|webp)", path):
        return f"https://image.tmdb.org/t/p/{size}{path}"
    return None


def render_item(item: dict[str, Any], *, full: bool) -> str:
    kind = "Película" if item["media_type"] == "movie" else "Serie"
    released = item.get("release_date") or item.get("first_air_date")
    summary = [display_title(item), kind, f"TMDB {item['id']}"]
    if released:
        summary.append(released)
    if item.get("vote_count"):
        summary.append(f"{item['vote_average']:.1f}/10 ({item['vote_count']} votos)")
    lines = [" · ".join(summary)]
    genres = ", ".join(genre["name"] for genre in item.get("genres", []))
    if genres:
        lines.append(genres)
    if item.get("runtime"):
        lines.append(f"{item['runtime']} min")
    if item.get("number_of_seasons"):
        lines.append(f"Temporadas · {item['number_of_seasons']}")
    if item.get("status"):
        lines.append(str(item["status"]))
    if item.get("overview"):
        overview = str(item["overview"])
        lines.append(overview if full else overview[:230] + ("…" if len(overview) > 230 else ""))
    poster = image_url(item.get("poster_path"))
    if poster:
        lines.append(f"Póster · {poster}")
    lines.append(tmdb_link(item))
    return "\n".join(lines)


def render_list(label: str, items: list[dict[str, Any]], limit: int) -> str:
    rows = [render_item(item, full=len(items) <= 2) for item in items[:limit]]
    return "\n\n".join([label, *(rows or ["Sin resultados."]), "Datos e imágenes de TMDB."])


def render_groups(
    label: str, kinds: tuple[str, ...], groups: list[dict[str, Any]], limit: int,
) -> str:
    sections = []
    for kind, group in zip(kinds, groups, strict=True):
        heading = "Películas" if kind == "movie" else "Series"
        items = typed_results(group, kind)
        sections.extend([heading, *(render_item(item, full=False) for item in items[:limit])])
        if not items:
            sections.append("Sin resultados.")
        if group.get("page", 1) < group.get("total_pages", 1):
            sections.append(f"Página {group.get('page', 1)} · hay más resultados.")
    return "\n\n".join([label, *sections, "Datos e imágenes de TMDB."])


def render_episode(item: dict[str, Any]) -> str:
    lines = [display_title(item)]
    for field, label in (("next_episode_to_air", "Próximo"), ("last_episode_to_air", "Último")):
        episode = item.get(field)
        if episode:
            air_date = episode.get("air_date") or "fecha sin anunciar"
            lines.append(
                f"{label} · T{episode['season_number']:02d}E{episode['episode_number']:02d} "
                f"· {episode.get('name') or 'Sin título'} · {air_date}"
            )
            still = image_url(episode.get("still_path"), "w300")
            if still and field == "next_episode_to_air":
                lines.append(f"Imagen · {still}")
        elif field == "next_episode_to_air":
            lines.append("TMDB no registra un próximo episodio anunciado.")
    if item.get("status"):
        lines.append(f"Estado en TMDB · {item['status']}")
    poster = image_url(item.get("poster_path"))
    if poster:
        lines.append(f"Póster · {poster}")
    return "\n".join([*lines, tmdb_link(item), "Datos e imágenes de TMDB."])
