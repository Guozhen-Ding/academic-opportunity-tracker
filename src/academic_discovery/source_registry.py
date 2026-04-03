from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from academic_discovery.fetchers.academicjobsonline_jobs import AcademicJobsOnlineFetcher
from academic_discovery.fetchers.cambridge_jobs import CambridgeJobsFetcher
from academic_discovery.fetchers.epfl_jobs import EPFLJobsFetcher
from academic_discovery.fetchers.eth_jobs import ETHJobsFetcher
from academic_discovery.fetchers.euraxess_jobs import EuraxessJobsFetcher
from academic_discovery.fetchers.generic import GenericOpportunityFetcher
from academic_discovery.fetchers.imperial_fellowships import ImperialFellowshipsFetcher
from academic_discovery.fetchers.imperial_jobs import ImperialJobsFetcher
from academic_discovery.fetchers.jobs_ac_uk import JobsAcUkFetcher
from academic_discovery.fetchers.kuleuven_jobs import KULeuvenJobsFetcher
from academic_discovery.fetchers.leverhulme_listings import LeverhulmeListingsFetcher
from academic_discovery.fetchers.melbourne_jobs import MelbourneJobsFetcher
from academic_discovery.fetchers.nus_jobs import NUSJobsFetcher
from academic_discovery.fetchers.oxford_jobs import OxfordJobsFetcher
from academic_discovery.fetchers.royal_society_grants import RoyalSocietyGrantsFetcher
from academic_discovery.fetchers.tudelft_jobs import TUDelftJobsFetcher
from academic_discovery.fetchers.unsw_jobs import UNSWJobsFetcher
from academic_discovery.fetchers.ukri_opportunities import UKRIOpportunitiesFetcher
from academic_discovery.utils.text import slugify_query


FetcherFactory = Callable[[], Any]


@dataclass(frozen=True)
class SourceSpec:
    registry_key: str
    source_key: str
    kind: str
    config_section: str
    fetcher_name: str
    supports_dynamic: bool = False
    source_priority: int = 3
    refresh_hours_default: float = 24.0


@dataclass
class ResolvedSource:
    spec: SourceSpec
    source_key: str
    config_section: str
    name: str
    kind: str
    refresh_hours: float
    factory: FetcherFactory
    supports_dynamic: bool
    source_priority: int
    raw_config: dict[str, Any]


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec("jobs_ac_uk", "jobs_ac_uk_v3", "job", "jobs_ac_uk", "JobsAcUkFetcher", source_priority=2),
    SourceSpec("cambridge_jobs", "cambridge_jobs_v2", "job", "cambridge_jobs", "CambridgeJobsFetcher", source_priority=6),
    SourceSpec("imperial_jobs", "imperial_jobs_v4", "job", "imperial_jobs", "ImperialJobsFetcher", supports_dynamic=True, source_priority=6),
    SourceSpec("imperial_fellowships", "imperial_fellowships_v1", "fellowship", "imperial_fellowships", "ImperialFellowshipsFetcher", source_priority=7),
    SourceSpec("leverhulme_listings", "leverhulme_listings_v1", "fellowship", "leverhulme_listings", "LeverhulmeListingsFetcher", source_priority=6),
    SourceSpec("oxford_jobs", "oxford_jobs_v1", "job", "oxford_jobs", "OxfordJobsFetcher", source_priority=6),
    SourceSpec("royal_society_grants", "royal_society_grants_v4", "fellowship", "royal_society_grants", "RoyalSocietyGrantsFetcher", source_priority=6),
    SourceSpec("ukri_opportunities", "ukri_opportunities_v1", "mixed", "ukri_opportunities", "UKRIOpportunitiesFetcher", source_priority=4),
    SourceSpec("ukri_epsrc_fellowships", "ukri_epsrc_fellowships_v1", "fellowship", "ukri_epsrc_fellowships", "UKRIOpportunitiesFetcher", source_priority=7),
    SourceSpec("euraxess_jobs", "euraxess_jobs_v1", "mixed", "euraxess_jobs", "EuraxessJobsFetcher", source_priority=5),
    SourceSpec("epfl_jobs", "epfl_jobs_v1", "job", "epfl_jobs", "EPFLJobsFetcher", source_priority=6),
    SourceSpec("eth_jobs", "eth_jobs_v1", "job", "eth_jobs", "ETHJobsFetcher", source_priority=6),
    SourceSpec("academicjobsonline_jobs", "academicjobsonline_jobs_v1", "mixed", "academicjobsonline_jobs", "AcademicJobsOnlineFetcher", source_priority=5),
    SourceSpec("nus_jobs", "nus_jobs_v1", "job", "nus_jobs", "NUSJobsFetcher", source_priority=6),
    SourceSpec("unsw_jobs", "unsw_jobs_v1", "job", "unsw_jobs", "UNSWJobsFetcher", source_priority=6),
    SourceSpec("kuleuven_jobs", "kuleuven_jobs_v3", "job", "kuleuven_jobs", "KULeuvenJobsFetcher", source_priority=6),
    SourceSpec("tudelft_jobs", "tudelft_jobs_v3", "job", "tudelft_jobs", "TUDelftJobsFetcher", source_priority=6),
    SourceSpec("melbourne_jobs", "melbourne_jobs_v1", "job", "melbourne_jobs", "MelbourneJobsFetcher", source_priority=6),
)


SOURCE_SPEC_BY_KEY = {spec.registry_key: spec for spec in SOURCE_SPECS}


def default_sources_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for spec in SOURCE_SPECS:
        defaults[spec.config_section] = {
            "enabled": False,
            "type": spec.kind,
            "refresh_hours": spec.refresh_hours_default,
            "priority": spec.source_priority,
            "fetcher": spec.fetcher_name,
            "supports_dynamic": spec.supports_dynamic,
            "params": {},
        }
    defaults["generic"] = []
    return defaults


def resolve_sources(config: dict[str, Any]) -> list[ResolvedSource]:
    sources = config.get("sources", {})
    resolved: list[ResolvedSource] = []

    for spec in SOURCE_SPECS:
        source_config = sources.get(spec.config_section, {})
        if not isinstance(source_config, dict) or not source_config.get("enabled"):
            continue
        resolved.append(
            ResolvedSource(
                spec=spec,
                source_key=str(source_config.get("source_key") or spec.source_key),
                config_section=spec.config_section,
                name=str(source_config.get("name", spec.config_section)),
                kind=str(source_config.get("type", spec.kind)),
                refresh_hours=float(source_config.get("refresh_hours", spec.refresh_hours_default)),
                factory=_build_factory(spec, source_config),
                supports_dynamic=bool(source_config.get("supports_dynamic", spec.supports_dynamic)),
                source_priority=int(source_config.get("priority", spec.source_priority)),
                raw_config=source_config,
            )
        )

    for index, target in enumerate(sources.get("generic", [])):
        if not isinstance(target, dict) or not target.get("enabled", True):
            continue
        name = str(target.get("name", target.get("url", "generic source")) or "generic source")
        source_key = str(target.get("source_key") or f"generic_{index}_{slugify_query(name)}")
        refresh_hours = float(target.get("refresh_hours", 24))
        resolved.append(
            ResolvedSource(
                spec=SourceSpec(
                    registry_key="generic",
                    source_key=source_key,
                    kind=str(target.get("type", "fellowship")),
                    config_section="generic",
                    fetcher_name="GenericOpportunityFetcher",
                    supports_dynamic=False,
                    source_priority=int(target.get("priority", 1)),
                    refresh_hours_default=refresh_hours,
                ),
                source_key=source_key,
                config_section="generic",
                name=name,
                kind=str(target.get("type", "fellowship")),
                refresh_hours=refresh_hours,
                factory=lambda target=target: GenericOpportunityFetcher(target),
                supports_dynamic=False,
                source_priority=int(target.get("priority", 1)),
                raw_config=target,
            )
        )

    return resolved


def _build_factory(spec: SourceSpec, source_config: dict[str, Any]) -> FetcherFactory:
    params = dict(source_config.get("params", {}))
    base_url = str(source_config.get("base_url", "") or params.pop("base_url", ""))

    if spec.registry_key == "jobs_ac_uk":
        return lambda base_url=base_url, params=params: JobsAcUkFetcher(
            base_url=base_url,
            queries=params.get("queries", []),
            max_pages=int(params.get("max_pages", 1)),
        )
    if spec.registry_key == "cambridge_jobs":
        return lambda base_url=base_url, params=params: CambridgeJobsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 80)),
        )
    if spec.registry_key == "imperial_jobs":
        return lambda base_url=base_url, params=params: ImperialJobsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 40)),
            max_show_more_clicks=int(params.get("max_show_more_clicks", 8)),
        )
    if spec.registry_key == "imperial_fellowships":
        return lambda base_url=base_url, params=params: ImperialFellowshipsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 200)),
        )
    if spec.registry_key == "leverhulme_listings":
        return lambda base_url=base_url, params=params: LeverhulmeListingsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 20)),
        )
    if spec.registry_key == "oxford_jobs":
        return lambda base_url=base_url, params=params: OxfordJobsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 40)),
        )
    if spec.registry_key == "royal_society_grants":
        return lambda base_url=base_url, params=params: RoyalSocietyGrantsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 60)),
            max_pages=int(params.get("max_pages", 6)),
        )
    if spec.registry_key in {"ukri_opportunities", "ukri_epsrc_fellowships"}:
        return lambda base_url=base_url, params=params: UKRIOpportunitiesFetcher(
            base_url=base_url,
            max_pages=int(params.get("max_pages", 12)),
            max_results=int(params.get("max_results", 120)),
        )
    if spec.registry_key == "euraxess_jobs":
        return lambda base_url=base_url, params=params: EuraxessJobsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 80)),
        )
    if spec.registry_key == "epfl_jobs":
        return lambda base_url=base_url, params=params: EPFLJobsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 80)),
        )
    if spec.registry_key == "eth_jobs":
        return lambda base_url=base_url, params=params: ETHJobsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 80)),
        )
    if spec.registry_key == "academicjobsonline_jobs":
        return lambda base_url=base_url, params=params: AcademicJobsOnlineFetcher(
            base_url=base_url,
            boards=list(params.get("boards", [])) or None,
            max_results=int(params.get("max_results", 120)),
        )
    if spec.registry_key == "nus_jobs":
        return lambda base_url=base_url, params=params: NUSJobsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 80)),
        )
    if spec.registry_key == "unsw_jobs":
        return lambda base_url=base_url, params=params: UNSWJobsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 80)),
        )
    if spec.registry_key == "kuleuven_jobs":
        return lambda base_url=base_url, params=params: KULeuvenJobsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 80)),
        )
    if spec.registry_key == "tudelft_jobs":
        return lambda base_url=base_url, params=params: TUDelftJobsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 80)),
            max_pages=int(params.get("max_pages", 5)),
        )
    if spec.registry_key == "melbourne_jobs":
        return lambda base_url=base_url, params=params: MelbourneJobsFetcher(
            base_url=base_url,
            max_results=int(params.get("max_results", 80)),
        )
    raise KeyError(f"Unsupported source registry key: {spec.registry_key}")
