from __future__ import annotations

from datetime import date
from datetime import datetime
from difflib import SequenceMatcher
import json
from html import escape
from pathlib import Path
import re
from typing import Any

import pandas as pd

from academic_discovery.models import Opportunity

STATUS_BACKUP_RETENTION = 20


def write_outputs(
    opportunities: list[Opportunity],
    output_dir: str | Path,
    today: date | None = None,
    config_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    jobs = [item.to_record() for item in opportunities if item.type == "job"]
    fellowships = [item.to_record() for item in opportunities if item.type == "fellowship"]

    jobs_path = output_path / "jobs.csv"
    fellowships_path = output_path / "fellowships.csv"
    report_path = output_path / f"report-{today.isoformat()}.md"
    dashboard_path = output_path / "dashboard.html"
    dashboard_js_path = output_path / "dashboard.js"
    dashboard_css_path = output_path / "dashboard.css"

    previous_jobs = _read_existing(jobs_path)
    previous_fellowships = _read_existing(fellowships_path)

    pd.DataFrame(jobs).to_csv(jobs_path, index=False)
    pd.DataFrame(fellowships).to_csv(fellowships_path, index=False)

    report_body = render_report(
        jobs=jobs,
        fellowships=fellowships,
        previous_jobs=previous_jobs,
        previous_fellowships=previous_fellowships,
        today=today,
    )
    report_path.write_text(report_body, encoding="utf-8")
    dashboard_body = render_dashboard(
        jobs=jobs,
        fellowships=fellowships,
        previous_jobs=previous_jobs,
        previous_fellowships=previous_fellowships,
        today=today,
        config_snapshot=config_snapshot or {},
    )
    dashboard_html, dashboard_js, dashboard_css = _split_dashboard_assets(dashboard_body, today)
    dashboard_path.write_text(dashboard_html, encoding="utf-8")
    dashboard_js_path.write_text(dashboard_js, encoding="utf-8")
    dashboard_css_path.write_text(dashboard_css, encoding="utf-8")

    new_jobs = [item for item in jobs if item.get("url") not in previous_jobs]
    new_fellowships = [item for item in fellowships if item.get("url") not in previous_fellowships]

    return {
        "jobs": jobs_path,
        "fellowships": fellowships_path,
        "report": report_path,
        "dashboard": dashboard_path,
        "dashboard_js": dashboard_js_path,
        "dashboard_css": dashboard_css_path,
        "report_body": report_body,
        "new_jobs": new_jobs,
        "new_fellowships": new_fellowships,
    }


def render_report(
    jobs: list[dict],
    fellowships: list[dict],
    previous_jobs: set[str],
    previous_fellowships: set[str],
    today: date,
) -> str:
    new_jobs = [item for item in jobs if item.get("url") not in previous_jobs]
    new_fellowships = [item for item in fellowships if item.get("url") not in previous_fellowships]
    top_matches = sorted(jobs + fellowships, key=lambda item: item.get("match_score", 0), reverse=True)[:10]

    lines = [
        f"# Academic Opportunities Report - {today.isoformat()}",
        "",
        f"- New jobs: {len(new_jobs)}",
        f"- New fellowships: {len(new_fellowships)}",
        "",
        "## New Jobs",
    ]
    lines.extend(_render_items(new_jobs[:15]))
    lines.append("")
    lines.append("## New Fellowships")
    lines.extend(_render_items(new_fellowships[:15]))
    lines.append("")
    lines.append("## High-Match Opportunities")
    lines.extend(_render_items(top_matches))
    lines.append("")
    return "\n".join(lines)


def _render_items(items: list[dict]) -> list[str]:
    if not items:
        return ["- None."]
    lines: list[str] = []
    for item in items:
        lines.append(
            "- [{title}]({url}) | {institution} | score={score} | deadline={deadline} | {reason}".format(
                title=item.get("title", "Untitled"),
                url=item.get("url", ""),
                institution=item.get("institution", ""),
                score=item.get("match_score", 0),
                deadline=item.get("application_deadline") or item.get("deadline_status", "unknown"),
                reason=item.get("match_reason", ""),
            )
        )
    return lines


def _read_existing(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        frame = pd.read_csv(path)
    except Exception:
        return set()
    if "url" not in frame.columns:
        return set()
    return {str(value) for value in frame["url"].dropna().tolist()}


def _read_existing_status_store(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        frame = pd.read_csv(path, keep_default_na=False)
    except Exception:
        return {}
    if "url" not in frame.columns:
        return {}
    if "status" not in frame.columns:
        frame["status"] = ""
    if "note" not in frame.columns:
        frame["note"] = ""
    if "title" not in frame.columns:
        frame["title"] = ""
    if "institution" not in frame.columns:
        frame["institution"] = ""
    statuses: dict[str, dict[str, str]] = {}
    for _, row in frame[["url", "status", "note", "title", "institution"]].dropna(subset=["url"]).iterrows():
        status_value = str(row.get("status", "") or "")
        note_value = str(row.get("note", "") or "")
        statuses[str(row["url"])] = {
            "status": "" if status_value.lower() == "nan" else status_value,
            "note": "" if note_value.lower() == "nan" else note_value,
            "title": str(row.get("title", "") or ""),
            "institution": str(row.get("institution", "") or ""),
        }
    return statuses


def _normalize_match_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (value or "").lower())).strip()


def _normalize_match_title(value: str) -> str:
    return _normalize_match_text(value)


def _normalize_match_institution(value: str) -> str:
    raw = (value or "").lower()
    for splitter in [" - ", " / ", " | "]:
        if splitter in raw:
            raw = raw.split(splitter, 1)[0].strip()
            break
    normalized = _normalize_match_text(raw)
    for splitter in [" department ", " school ", " faculty ", " college ", " laboratory ", " institute "]:
        if splitter in normalized:
            normalized = normalized.split(splitter, 1)[0].strip()
    return normalized


def _build_status_fallbacks(statuses: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    fallbacks: list[dict[str, str]] = []
    for payload in statuses.values():
        title = str(payload.get("title", "") or "").strip()
        institution = str(payload.get("institution", "") or "").strip()
        status = str(payload.get("status", "") or "").strip()
        if not title or not institution or not status:
            continue
        fallbacks.append(
            {
                "title": title,
                "institution": institution,
                "title_norm": _normalize_match_title(title),
                "institution_norm": _normalize_match_institution(institution),
                "status": status,
                "note": str(payload.get("note", "") or ""),
            }
        )
    return fallbacks


def _resolve_saved_state(
    item: dict[str, Any],
    previous_statuses: dict[str, dict[str, str]],
    fallback_statuses: list[dict[str, str]],
) -> dict[str, str]:
    url = str(item.get("url", "") or "").strip()
    direct = previous_statuses.get(url)
    if direct:
        return direct

    title_norm = _normalize_match_title(str(item.get("title", "") or ""))
    institution_norm = _normalize_match_institution(str(item.get("institution", "") or ""))
    if not title_norm or not institution_norm:
        return {}

    best: dict[str, str] | None = None
    best_score = 0.0
    for candidate in fallback_statuses:
        if candidate["institution_norm"] != institution_norm:
            continue
        similarity = SequenceMatcher(None, title_norm, candidate["title_norm"]).ratio()
        if similarity >= 0.94 and similarity > best_score:
            best = candidate
            best_score = similarity
    if not best:
        return {}
    return {
        "status": best.get("status", ""),
        "note": best.get("note", ""),
    }


def _write_statuses(path: Path, items: list[dict[str, Any]]) -> None:
    latest_statuses = _read_existing_status_store(path)
    _backup_status_store(path)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    # Preserve the latest statuses already on disk, including updates made
    # while a background refresh was running.
    for url, payload in latest_statuses.items():
        clean_url = str(url or "").strip()
        if not clean_url or clean_url in seen:
            continue
        seen.add(clean_url)
        rows.append({
            "url": clean_url,
            "status": str(payload.get("status", "") or ""),
            "note": str(payload.get("note", "") or ""),
            "type": "",
            "title": "",
            "institution": str(payload.get("institution", "") or ""),
        })

    for item in items:
        url = str(item.get("url", "") or "").strip()
        incoming_status = str(item.get("status", "") or "").strip()
        incoming_note = str(item.get("note", "") or "")
        latest = latest_statuses.get(url, {})
        latest_status = str(latest.get("status", "") or "").strip()
        latest_note = str(latest.get("note", "") or "")
        effective_status = incoming_status or latest_status
        effective_note = incoming_note if incoming_note or incoming_note == "" else latest_note
        if not url or url in seen:
            if not url:
                continue
            for row in rows:
                if row["url"] == url:
                    row["status"] = effective_status or row.get("status", "")
                    row["note"] = effective_note if effective_note or effective_note == "" else row.get("note", "")
                    row["type"] = str(item.get("type", row.get("type", "")) or row.get("type", ""))
                    row["title"] = str(item.get("title", row.get("title", "")) or row.get("title", ""))
                    row["institution"] = str(item.get("institution", row.get("institution", "")) or row.get("institution", ""))
                    break
            continue
        seen.add(url)
        rows.append({
            "url": url,
            "status": effective_status,
            "note": effective_note,
            "type": str(item.get("type", "") or ""),
            "title": str(item.get("title", "") or ""),
            "institution": str(item.get("institution", "") or ""),
        })
    pd.DataFrame(rows, columns=["url", "status", "note", "type", "title", "institution"]).to_csv(path, index=False)


def _backup_status_store(path: Path) -> None:
    if not path.exists():
        return
    backup_dir = path.parent / "status_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"statuses-{timestamp}.csv"
    try:
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        return
    _prune_status_backups(backup_dir)


def _prune_status_backups(backup_dir: Path, keep: int = STATUS_BACKUP_RETENTION) -> None:
    try:
        backups = sorted(
            backup_dir.glob("statuses-*.csv"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return
    for stale_backup in backups[keep:]:
        try:
            stale_backup.unlink()
        except Exception:
            continue


def render_email_summary(
    new_jobs: list[dict[str, Any]],
    new_fellowships: list[dict[str, Any]],
    today: date,
    max_items: int = 10,
) -> str:
    new_items = sorted(
        new_jobs + new_fellowships,
        key=lambda item: item.get("match_score", 0),
        reverse=True,
    )
    selected = new_items[:max_items]

    lines = [
        f"Academic opportunities summary for {today.isoformat()}",
        "",
        f"New jobs: {len(new_jobs)}",
        f"New fellowships: {len(new_fellowships)}",
        "",
    ]

    if not selected:
        lines.append("No new matching opportunities were found today.")
        return "\n".join(lines)

    lines.append("Top new matches:")
    lines.append("")
    for item in selected:
        lines.append(f"Title: {item.get('title', 'Untitled')}")
        lines.append(f"Type: {item.get('type', '')}")
        lines.append(f"Institution: {item.get('institution', '')}")
        lines.append(f"Score: {item.get('match_score', 0)}")
        lines.append(f"Deadline: {item.get('application_deadline') or item.get('deadline_status', 'unknown')}")
        lines.append(f"Why it matches: {item.get('match_reason', '')}")
        lines.append(f"URL: {item.get('url', '')}")
        lines.append("")
    return "\n".join(lines)


def _split_dashboard_assets(dashboard_body: str, today: date) -> tuple[str, str, str]:
    style_start = dashboard_body.find("<style>")
    style_end = dashboard_body.find("</style>")
    script_start = dashboard_body.rfind("<script>")
    script_end = dashboard_body.rfind("</script>")
    if style_start == -1 or style_end == -1 or script_start == -1 or script_end == -1 or script_end <= script_start:
        return dashboard_body, "", ""
    style_body = dashboard_body[style_start + len("<style>"):style_end].strip()
    script_body = dashboard_body[script_start + len("<script>"):script_end].strip()
    version = f"{today.isoformat()}-{datetime.now().strftime('%H%M%S')}"
    legacy_script = """
<script>
(function(){
  function el(id){ return document.getElementById(id); }
  function txt(node){ return (node && (node.innerText || node.textContent) || '').replace(/^\\s+|\\s+$/g, ''); }
  function lower(value){ return String(value || '').toLowerCase(); }
  function setIndicator(message){
    var indicator = el('serverIndicatorText');
    if (indicator) { indicator.textContent = message; }
  }
  function splitTerms(text){
    var parts = String(text || '').split(/[\\n,]+/);
    var out = [];
    var seen = {};
    var i, term, key;
    for (i = 0; i < parts.length; i += 1) {
      term = parts[i].replace(/^\\s+|\\s+$/g, '');
      key = lower(term);
      if (term && !seen[key]) {
        seen[key] = true;
        out.push(term);
      }
    }
    return out;
  }
  function byIdOrAll(select, value){
    return !select || select.value === 'all' || lower(value) === lower(select.value);
  }
  function uniqueValuesFromCards(attr){
    var cards = getCards();
    var seen = {};
    var values = [];
    var i, value, key;
    for (i = 0; i < cards.length; i += 1) {
      value = cards[i].getAttribute(attr) || '';
      value = value.replace(/^\\s+|\\s+$/g, '');
      key = lower(value);
      if (value && !seen[key]) {
        seen[key] = true;
        values.push(value);
      }
    }
    values.sort();
    return values;
  }
  function populateSelect(id, attr, label){
    var select = el(id);
    var values = uniqueValuesFromCards(attr);
    var html = ['<option value=\"all\">' + label + '</option>'];
    var i;
    if (!select) { return; }
    for (i = 0; i < values.length; i += 1) {
      html.push('<option value=\"' + values[i].replace(/\"/g, '&quot;') + '\">' + values[i] + '</option>');
    }
    select.innerHTML = html.join('');
  }
  function getCards(){
    return Array.prototype.slice.call(document.querySelectorAll('#results article.card'));
  }
  function getCardMeta(card, label){
    var nodes = card.querySelectorAll('.grid > div');
    var i, strong, text;
    for (i = 0; i < nodes.length; i += 1) {
      strong = nodes[i].querySelector('strong');
      if (strong && lower(txt(strong)) === lower(label)) {
        text = txt(nodes[i]).replace(txt(strong), '').replace(/^\\s+|\\s+$/g, '');
        return text;
      }
    }
    return '';
  }
  function currentStatus(card){
    var active = card.querySelector('.status-btn.active');
    if (!active) { return ''; }
    var value = active.getAttribute('data-status') || '';
    return value === 'none' ? '' : value;
  }
  function updateStatusButtons(card, status){
    var buttons = card.querySelectorAll('.status-btn');
    var i, button, value;
    for (i = 0; i < buttons.length; i += 1) {
      button = buttons[i];
      value = button.getAttribute('data-status') || '';
      if ((status === '' && value === 'none') || value === status) {
        button.className = button.className.replace(/\\s*active/g, '') + ' active';
      } else {
        button.className = button.className.replace(/\\s*active/g, '');
      }
    }
    card.setAttribute('data-status-current', status);
  }
  function postJson(url, payload, callback){
    var xhr = new XMLHttpRequest();
    xhr.open('POST', url, true);
    xhr.setRequestHeader('Content-Type', 'application/json;charset=UTF-8');
    xhr.onreadystatechange = function(){
      if (xhr.readyState === 4) {
        callback(xhr.status >= 200 && xhr.status < 300, xhr.responseText);
      }
    };
    xhr.send(JSON.stringify(payload));
  }
  function getState(){
    return {
      search: lower(el('search') && el('search').value),
      type: el('typeFilter') ? el('typeFilter').value : 'all',
      onlyNew: el('newFilter') ? el('newFilter').value === 'new' : false,
      deadline: el('deadlineFilter') ? el('deadlineFilter').value : 'all',
      source: el('sourceFilter'),
      country: el('countryFilter'),
      institution: el('institutionFilter'),
      highMatchOnly: !!(el('toggleHighMatch') && /active/.test(el('toggleHighMatch').className)),
      hideInterested: !!(el('toggleInterested') && /active/.test(el('toggleInterested').className)),
      hideApplied: !!(el('toggleApplied') && /active/.test(el('toggleApplied').className)),
      hideIgnored: !!(el('toggleIgnored') && /active/.test(el('toggleIgnored').className))
    };
  }
  function parseDays(value){
    var n = parseInt(value, 10);
    return isNaN(n) ? 999999 : n;
  }
  function parseScore(value){
    var n = parseFloat(value);
    return isNaN(n) ? 0 : n;
  }
  function sortCards(cards){
    var sortBy = el('sortBy') ? el('sortBy').value : 'deadline_asc';
    cards.sort(function(a, b){
      if (sortBy === 'deadline_desc') {
        return parseDays(b.getAttribute('data-days-left')) - parseDays(a.getAttribute('data-days-left'));
      }
      if (sortBy === 'score_desc') {
        return parseScore(b.getAttribute('data-match-score')) - parseScore(a.getAttribute('data-match-score'));
      }
      if (sortBy === 'title_asc') {
        return lower(a.getAttribute('data-title')).localeCompare(lower(b.getAttribute('data-title')));
      }
      return parseDays(a.getAttribute('data-days-left')) - parseDays(b.getAttribute('data-days-left'));
    });
  }
  function applyFilters(){
    var results = el('results');
    var cards = getCards();
    var state = getState();
    var visible = [];
    var i, card, text, type, status, days, score, show;
    for (i = 0; i < cards.length; i += 1) {
      card = cards[i];
      text = lower(txt(card));
      type = lower(card.getAttribute('data-type'));
      status = lower(card.getAttribute('data-status-current'));
      days = parseDays(card.getAttribute('data-days-left'));
      score = parseScore(card.getAttribute('data-match-score'));
      show = true;
      if (state.search && text.indexOf(state.search) === -1) { show = false; }
      if (state.type !== 'all' && type !== lower(state.type)) { show = false; }
      if (state.onlyNew && card.getAttribute('data-is-new') !== 'true') { show = false; }
      if (state.deadline === '7' && days > 7) { show = false; }
      if (state.deadline === '14' && days > 14) { show = false; }
      if (state.deadline === '30' && days > 30) { show = false; }
      if (!byIdOrAll(state.source, card.getAttribute('data-source'))) { show = false; }
      if (!byIdOrAll(state.country, card.getAttribute('data-country'))) { show = false; }
      if (!byIdOrAll(state.institution, card.getAttribute('data-institution'))) { show = false; }
      if (state.highMatchOnly && score < 0.1) { show = false; }
      if (state.hideInterested && status === 'interested') { show = false; }
      if (state.hideApplied && status === 'applied') { show = false; }
      if (state.hideIgnored && status === 'ignored') { show = false; }
      card.style.display = show ? '' : 'none';
      if (show) { visible.push(card); }
    }
    sortCards(visible);
    for (i = 0; i < visible.length; i += 1) {
      results.appendChild(visible[i]);
    }
    updateHeroCounts(cards);
  }
  function updateHeroCounts(cards){
    var jobs = 0, fellowships = 0, interested = 0, applied = 0, ignored = 0, i, card, type, status;
    for (i = 0; i < cards.length; i += 1) {
      card = cards[i];
      type = lower(card.getAttribute('data-type'));
      status = lower(card.getAttribute('data-status-current'));
      if (type === 'job') { jobs += 1; }
      if (type === 'fellowship') { fellowships += 1; }
      if (status === 'interested') { interested += 1; }
      if (status === 'applied') { applied += 1; }
      if (status === 'ignored') { ignored += 1; }
    }
    if (el('heroJobsCount')) { el('heroJobsCount').textContent = jobs; }
    if (el('heroFellowshipsCount')) { el('heroFellowshipsCount').textContent = fellowships; }
    if (el('heroInterestedCount')) { el('heroInterestedCount').textContent = interested; }
    if (el('heroAppliedCount')) { el('heroAppliedCount').textContent = applied; }
    if (el('heroIgnoredCount')) { el('heroIgnoredCount').textContent = ignored; }
    var statCards = document.querySelectorAll('[data-stat-action]');
    for (i = 0; i < statCards.length; i += 1) {
      var action = statCards[i].getAttribute('data-stat-action');
      var strong = statCards[i].getElementsByTagName('strong')[0];
      if (!strong) { continue; }
      if (action === 'jobs') { strong.textContent = jobs; }
      if (action === 'fellowships') { strong.textContent = fellowships; }
      if (action === 'interested') { strong.textContent = interested; }
      if (action === 'applied') { strong.textContent = applied; }
      if (action === 'ignored') { strong.textContent = ignored; }
    }
  }
  function toggleButtonState(button){
    if (!button) { return; }
    if (/active/.test(button.className)) {
      button.className = button.className.replace(/\\s*active/g, '');
    } else {
      button.className += ' active';
    }
  }
  function bindEvents(){
    var i, buttons, controls, button, url;
    populateSelect('sourceFilter', 'data-source', 'All source sites');
    populateSelect('countryFilter', 'data-country', 'All countries');
    populateSelect('institutionFilter', 'data-institution', 'All institutions');
    controls = ['search','typeFilter','newFilter','deadlineFilter','sortBy','sourceFilter','countryFilter','institutionFilter'];
    for (i = 0; i < controls.length; i += 1) {
      if (el(controls[i])) {
        el(controls[i]).onchange = applyFilters;
        el(controls[i]).onkeyup = applyFilters;
      }
    }
    buttons = ['toggleHighMatch','toggleInterested','toggleApplied','toggleIgnored'];
    for (i = 0; i < buttons.length; i += 1) {
      if (el(buttons[i])) {
        el(buttons[i]).onclick = (function(btn){
          return function(){
            toggleButtonState(btn);
            applyFilters();
            return false;
          };
        })(el(buttons[i]));
      }
    }
    var actionCards = document.querySelectorAll('[data-stat-action]');
    for (i = 0; i < actionCards.length; i += 1) {
      actionCards[i].onclick = function(){
        var action = this.getAttribute('data-stat-action');
        if (action === 'jobs' && el('typeFilter')) { el('typeFilter').value = 'job'; }
        if (action === 'fellowships' && el('typeFilter')) { el('typeFilter').value = 'fellowship'; }
        if (action === 'new-jobs' && el('typeFilter') && el('newFilter')) { el('typeFilter').value = 'job'; el('newFilter').value = 'new'; }
        if (action === 'new-fellowships' && el('typeFilter') && el('newFilter')) { el('typeFilter').value = 'fellowship'; el('newFilter').value = 'new'; }
        if (action === 'interested' && el('toggleInterested') && !/active/.test(el('toggleInterested').className)) { toggleButtonState(el('toggleInterested')); }
        if (action === 'applied' && el('toggleApplied') && !/active/.test(el('toggleApplied').className)) { toggleButtonState(el('toggleApplied')); }
        if (action === 'ignored' && el('toggleIgnored')) { toggleButtonState(el('toggleIgnored')); }
        applyFilters();
        return false;
      };
    }
    var statusButtons = document.querySelectorAll('.status-btn');
    for (i = 0; i < statusButtons.length; i += 1) {
      statusButtons[i].onclick = function(){
        var btn = this;
        var card = btn;
        while (card && (!card.className || card.className.indexOf('card') === -1)) { card = card.parentNode; }
        postJson('/api/status', {url: btn.getAttribute('data-url'), status: btn.getAttribute('data-status') === 'none' ? '' : btn.getAttribute('data-status')}, function(ok){
          if (ok && card) {
            updateStatusButtons(card, btn.getAttribute('data-status') === 'none' ? '' : btn.getAttribute('data-status'));
            setIndicator('Legacy controls active');
            applyFilters();
          } else {
            setIndicator('Status save failed');
          }
        });
        return false;
      };
    }
    var keywordButtons = document.querySelectorAll('[data-keyword-filter]');
    for (i = 0; i < keywordButtons.length; i += 1) {
      keywordButtons[i].onclick = function(){
        if (el('search')) { el('search').value = this.getAttribute('data-keyword-filter') || ''; }
        applyFilters();
        return false;
      };
    }
    if (el('clearKeywordFilter')) {
      el('clearKeywordFilter').onclick = function(){
        if (el('search')) { el('search').value = ''; }
        applyFilters();
        return false;
      };
    }
    if (el('saveConfigButton')) {
      el('saveConfigButton').onclick = function(){
        postJson('/api/config', {
          keywords: splitTerms(el('keywordsEditor') && el('keywordsEditor').value),
          exclude_terms: splitTerms(el('excludeTermsEditor') && el('excludeTermsEditor').value),
          protected_terms: splitTerms(el('protectedTermsEditor') && el('protectedTermsEditor').value),
          expanded_terms: splitTerms(el('expandedTermsEditor') && el('expandedTermsEditor').value)
        }, function(ok){
          setIndicator(ok ? 'Settings saved' : 'Settings save failed');
        });
        return false;
      };
    }
    if (el('restoreStatusesButton')) {
      el('restoreStatusesButton').onclick = function(){
        postJson('/api/restore-statuses', {}, function(ok){
          setIndicator(ok ? 'Statuses restored' : 'Restore failed');
          window.location.reload();
        });
        return false;
      };
    }
  }
  bindEvents();
  setIndicator('Legacy controls active');
  applyFilters();
})();
</script>
""".strip()
    html = (
        dashboard_body[:style_start]
        + f'<link rel="stylesheet" href="dashboard.css?v={version}">'
        + dashboard_body[style_end + len("</style>"):script_start]
        + (
            "<script>"
            "(function(){"
            "function setMsg(msg){var el=document.getElementById('serverIndicatorText');if(el){el.textContent=msg;}}"
            "window.addEventListener('error',function(e){setMsg('JS error: '+(e.message||'unknown error'));});"
            "window.addEventListener('unhandledrejection',function(e){"
            "var reason=e&&e.reason;"
            "setMsg('Promise error: '+((reason&&reason.message)||String(reason||'unknown error')));"
            "});"
            "})();"
            "</script>"
        )
        + legacy_script
        + (
            '<script '
            f'src="dashboard.js?v={version}" '
            'onload="(function(){var el=document.getElementById(\'serverIndicatorText\');'
            'if(el&&el.textContent===\'Checking server connection...\'){'
            'el.textContent=\'Dashboard script loaded\';}})()" '
            'onerror="(function(){var el=document.getElementById(\'serverIndicatorText\');'
            'if(el){el.textContent=\'Dashboard script failed to load\';}})()">'
            "</script>"
        )
        + dashboard_body[script_end + len("</script>"):]
    )
    return html, script_body, style_body


def render_dashboard(
    jobs: list[dict[str, Any]],
    fellowships: list[dict[str, Any]],
    previous_jobs: set[str],
    previous_fellowships: set[str],
    today: date,
    config_snapshot: dict[str, Any],
) -> str:
    all_items: list[dict[str, Any]] = []
    for item in jobs:
        item_copy = dict(item)
        item_copy["is_new"] = item.get("url") not in previous_jobs
        all_items.append(item_copy)
    for item in fellowships:
        item_copy = dict(item)
        item_copy["is_new"] = item.get("url") not in previous_fellowships
        all_items.append(item_copy)

    all_items.sort(key=lambda row: (float(row.get("match_score", 0)), -(row.get("days_left") or 9999)), reverse=True)
    interested_count = sum(1 for item in all_items if str(item.get("status", "") or "").strip() == "interested")
    applied_count = sum(1 for item in all_items if str(item.get("status", "") or "").strip() == "applied")
    ignored_count = sum(1 for item in all_items if str(item.get("status", "") or "").strip() == "ignored")
    unprocessed_items = [item for item in all_items if not str(item.get("status", "") or "").strip()]
    interested_items = [item for item in all_items if str(item.get("status", "") or "").strip() == "interested"]
    applied_items = [item for item in all_items if str(item.get("status", "") or "").strip() == "applied"]
    initial_items = unprocessed_items if unprocessed_items else interested_items
    initial_results_html = "".join(_render_initial_card(item) for item in initial_items[:40]) or '<div class="empty">No opportunities match the current filters.</div>'
    interested_focus_html = "".join(_render_initial_focus_item(item) for item in interested_items[:8]) or '<div class="empty">No items marked Interested yet.</div>'
    applied_focus_html = "".join(_render_initial_focus_item(item) for item in applied_items[:8]) or '<div class="empty">No items marked Applied yet.</div>'
    payload = "[]"
    config_payload = json.dumps(config_snapshot)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Academic Opportunities Dashboard</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;700&display=swap');

    :root {{
      --bg: #eef3f8;
      --bg-2: #f8fbfd;
      --panel: rgba(255, 255, 255, 0.78);
      --panel-strong: rgba(255, 255, 255, 0.95);
      --text: #102033;
      --muted: #5f7288;
      --accent: #1260ff;
      --accent-soft: rgba(18, 96, 255, 0.12);
      --accent-deep: #0a3ca8;
      --warn: #c77600;
      --warn-soft: rgba(255, 191, 71, 0.16);
      --danger: #c23645;
      --danger-soft: rgba(240, 86, 110, 0.14);
      --new: #0c8b66;
      --new-soft: rgba(12, 139, 102, 0.14);
      --line: rgba(138, 160, 187, 0.22);
      --shadow: 0 24px 60px rgba(19, 41, 66, 0.12);
      --shadow-soft: 0 12px 30px rgba(19, 41, 66, 0.08);
      --radius-xl: 28px;
      --radius-lg: 22px;
      --radius-md: 16px;
    }}

    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 0% 0%, rgba(18, 96, 255, 0.14), transparent 28%),
        radial-gradient(circle at 100% 0%, rgba(22, 196, 127, 0.14), transparent 24%),
        radial-gradient(circle at 50% 100%, rgba(255, 191, 71, 0.1), transparent 25%),
        linear-gradient(180deg, var(--bg-2) 0%, var(--bg) 100%);
      color: var(--text);
    }}

    .wrap {{
      max-width: 1320px;
      margin: 0 auto;
      padding: 32px 20px 64px;
    }}

    .hero {{
      display: grid;
      gap: 18px;
      padding: 30px;
      border: 1px solid var(--line);
      border-radius: var(--radius-xl);
      background:
        linear-gradient(135deg, rgba(255,255,255,0.94), rgba(245,250,255,0.86)),
        rgba(255,255,255,0.7);
      backdrop-filter: blur(14px);
      box-shadow: var(--shadow);
      position: relative;
      overflow: hidden;
    }}

    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -60px -80px auto;
      width: 220px;
      height: 220px;
      background: radial-gradient(circle, rgba(18, 96, 255, 0.16), transparent 65%);
      pointer-events: none;
    }}

    .hero h1 {{
      margin: 0;
      font-family: "Space Grotesk", "IBM Plex Sans", sans-serif;
      font-size: clamp(2rem, 4vw, 3.5rem);
      line-height: 0.95;
      letter-spacing: -0.05em;
    }}

    .hero p {{
      margin: 0;
      max-width: 760px;
      color: var(--muted);
      font-size: 1rem;
    }}

    .server-indicator {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      align-self: start;
      margin-top: 10px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.88);
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 0.84rem;
      font-weight: 600;
      box-shadow: var(--shadow-soft);
    }}

    .server-dot {{
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #9aa9b9;
    }}

    .server-indicator.connected .server-dot {{
      background: #0c8b66;
    }}

    .server-indicator.js-active {{
      border-color: rgba(12, 139, 102, 0.22);
    }}

    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 8px;
    }}

    .stat {{
      padding: 16px 18px;
      border-radius: 18px;
      background: var(--panel-strong);
      border: 1px solid var(--line);
      box-shadow: var(--shadow-soft);
    }}

    .stat.actionable,
    .summary-box.actionable {{
      cursor: pointer;
      transition: transform 140ms ease, box-shadow 140ms ease, border-color 140ms ease;
    }}

    .stat.actionable:hover,
    .summary-box.actionable:hover {{
      transform: translateY(-2px);
      box-shadow: 0 22px 38px rgba(18, 38, 63, 0.12);
      border-color: rgba(38, 93, 171, 0.34);
    }}

    .stat.active-filter,
    .summary-box.active-filter {{
      border-color: rgba(38, 93, 171, 0.42);
      background: rgba(228, 238, 251, 0.95);
    }}

    .stat strong {{
      display: block;
      font-family: "Space Grotesk", "IBM Plex Sans", sans-serif;
      font-size: 1.6rem;
      margin-bottom: 4px;
    }}

    .controls {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      margin: 0;
    }}

    .layout {{
      display: grid;
      grid-template-columns: minmax(320px, 360px) minmax(0, 1fr);
      gap: 22px;
      align-items: start;
      margin-top: 20px;
    }}

    .sidebar {{
      position: sticky;
      top: 18px;
      display: grid;
      gap: 16px;
      max-height: calc(100vh - 36px);
      overflow: auto;
      padding-right: 8px;
    }}

    .sidebar-panel {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow);
      padding: 20px;
      backdrop-filter: blur(14px);
    }}

    .sidebar-panel h3 {{
      margin: 0 0 10px;
      font-size: 1rem;
      font-family: "Space Grotesk", "IBM Plex Sans", sans-serif;
    }}

    .sidebar-panel p {{
      margin: 0 0 12px;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.45;
    }}

    .sidebar-group {{
      display: grid;
      gap: 10px;
      margin-top: 16px;
      padding-top: 16px;
      border-top: 1px solid rgba(129, 154, 186, 0.16);
    }}

    .sidebar-group:first-of-type {{
      margin-top: 0;
      padding-top: 0;
      border-top: 0;
    }}

    .sidebar-label {{
      margin: 0 0 2px;
      color: var(--muted);
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-weight: 700;
    }}

    .sidebar-note {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 0.84rem;
      line-height: 1.45;
    }}

    .main-column {{
      min-width: 0;
    }}

    .presets {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin: 0;
    }}

    .preset {{
      appearance: none;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
      color: var(--text);
      padding: 11px 12px;
      border-radius: 14px;
      font: inherit;
      cursor: pointer;
      box-shadow: var(--shadow-soft);
      text-align: left;
    }}

    .preset.active {{
      background: linear-gradient(180deg, rgba(18, 96, 255, 0.14), rgba(18, 96, 255, 0.18));
      border-color: rgba(18, 96, 255, 0.22);
      color: var(--accent-deep);
    }}

    .toolbar {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin: 0;
    }}

    .settings-panel {{
      margin: 0;
      padding: 0;
      border-radius: 0;
      border: 0;
      background: transparent;
      box-shadow: none;
      backdrop-filter: none;
    }}

    .settings-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      margin-bottom: 14px;
    }}

    .settings-head h3 {{
      margin: 0;
      font-family: "Space Grotesk", "IBM Plex Sans", sans-serif;
      font-size: 1.05rem;
    }}

    .settings-head p {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
    }}

    .settings-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 14px;
    }}

    .settings-field {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}

    .settings-field label {{
      font-weight: 600;
      color: var(--ink);
    }}

    .settings-field textarea {{
      min-height: 110px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.88);
      padding: 14px 15px;
      font: inherit;
      color: var(--ink);
      resize: vertical;
      outline: none;
    }}

    .settings-field textarea:focus {{
      border-color: rgba(38, 93, 171, 0.4);
      box-shadow: 0 0 0 4px rgba(38, 93, 171, 0.08);
    }}

    .settings-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: stretch;
      margin-top: 16px;
    }}

    .settings-note {{
      color: var(--muted);
      font-size: 0.88rem;
    }}

    .settings-head.compact {{
      margin: 18px 0 10px;
    }}

    .source-health {{
      margin-top: 18px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }}

    .source-health-list {{
      display: grid;
      gap: 10px;
    }}

    .source-health-item {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.84);
      border-radius: 14px;
      padding: 10px 12px;
      box-shadow: var(--shadow-soft);
    }}

    .source-health-item.error {{
      border-color: rgba(194, 54, 69, 0.25);
      background: rgba(255, 243, 245, 0.95);
    }}

    .source-health-item strong {{
      display: block;
      font-size: 0.92rem;
      margin-bottom: 4px;
    }}

    .source-health-meta {{
      color: var(--muted);
      font-size: 0.82rem;
      line-height: 1.45;
    }}

    .toggle {{
      appearance: none;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
      color: var(--text);
      padding: 11px 12px;
      border-radius: 14px;
      font: inherit;
      cursor: pointer;
      box-shadow: var(--shadow-soft);
      text-align: left;
    }}

    .toggle.active {{
      background: linear-gradient(180deg, #2d7bff, var(--accent));
      color: #fff;
      border-color: transparent;
    }}

    .controls input, .controls select {{
      width: 100%;
      min-height: 46px;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.82);
      color: var(--text);
      font: inherit;
      box-shadow: var(--shadow-soft);
    }}

    .sidebar .button {{
      width: 100%;
      justify-content: center;
      min-height: 46px;
    }}

    .results {{
      display: grid;
      gap: 14px;
    }}

    .summary-strip {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
      margin: 18px 0;
    }}

    .summary-box {{
      padding: 14px 16px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
      border-radius: 18px;
      box-shadow: var(--shadow-soft);
    }}

    .summary-box strong {{
      display: block;
      font-family: "Space Grotesk", "IBM Plex Sans", sans-serif;
      font-size: 1.25rem;
      margin-bottom: 3px;
    }}

    .summary-box span {{
      display: block;
    }}

    .summary-box small,
    .stat small {{
      display: block;
      margin-top: 6px;
      color: var(--muted);
      font-size: 0.78rem;
    }}

    .priority {{
      margin: 20px 0 22px;
      border: 1px solid var(--line);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.88), rgba(244,248,255,0.96));
      border-radius: var(--radius-lg);
      padding: 18px;
      box-shadow: var(--shadow);
    }}

    .priority-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 12px;
    }}

    .priority-head h3 {{
      margin: 0;
      font-size: 1.2rem;
    }}

    .priority-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }}

    .priority-card {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.9);
      border-radius: 18px;
      padding: 14px;
      box-shadow: var(--shadow-soft);
    }}

    .priority-card a {{
      color: var(--text);
      text-decoration: none;
      font-weight: 700;
      line-height: 1.35;
    }}

    .priority-card p {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.45;
    }}

    .focus-panels {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
      margin: 0 0 20px;
    }}

    .focus-panel {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.82);
      border-radius: var(--radius-lg);
      padding: 18px;
      box-shadow: var(--shadow);
    }}

    .focus-panel h3 {{
      margin: 0 0 10px;
      font-size: 1.1rem;
    }}

    .focus-list {{
      display: grid;
      gap: 10px;
    }}

    .focus-item {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255,255,255,0.9);
      padding: 12px 14px;
      box-shadow: var(--shadow-soft);
    }}

    .focus-item a {{
      color: var(--text);
      text-decoration: none;
      font-weight: 700;
      line-height: 1.35;
    }}

    .focus-item p {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 0.9rem;
    }}

    .card {{
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      background: var(--panel);
      backdrop-filter: blur(12px);
      box-shadow: var(--shadow);
      padding: 18px 20px;
    }}

    .card-header {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      margin-bottom: 14px;
    }}

    .card h2 {{
      margin: 0 0 6px;
      font-family: "Space Grotesk", "IBM Plex Sans", sans-serif;
      font-size: 1.24rem;
      line-height: 1.25;
    }}

    .card h2 a {{
      color: var(--text);
      text-decoration: none;
    }}

    .card h2 a:hover {{
      color: var(--accent);
    }}

    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: flex-start;
      justify-content: flex-end;
    }}

    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid rgba(18, 96, 255, 0.15);
      background: linear-gradient(180deg, #2d7bff, var(--accent));
      color: #fffdf8;
      text-decoration: none;
      font-size: 0.92rem;
      white-space: nowrap;
      box-shadow: 0 12px 28px rgba(18, 96, 255, 0.22);
    }}

    .button.secondary {{
      background: rgba(255,255,255,0.86);
      color: var(--accent-deep);
      border-color: var(--line);
      box-shadow: var(--shadow-soft);
    }}

    .status-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 12px;
    }}

    .status-btn {{
      appearance: none;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.86);
      color: var(--text);
      padding: 8px 12px;
      border-radius: 999px;
      font: inherit;
      font-size: 0.88rem;
      cursor: pointer;
      box-shadow: var(--shadow-soft);
    }}

    .status-btn.active[data-status="interested"] {{
      background: var(--accent-soft);
      color: var(--accent-deep);
      border-color: rgba(13, 92, 99, 0.25);
    }}

    .status-btn.active[data-status="applied"] {{
      background: var(--new-soft);
      color: var(--new);
      border-color: rgba(28, 124, 84, 0.25);
    }}

    .status-btn.active[data-status="ignored"] {{
      background: rgba(95, 114, 136, 0.12);
      color: #56677b;
      border-color: rgba(95, 114, 136, 0.22);
    }}

    .tag {{
      display: inline-flex;
      align-items: center;
      padding: 5px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      font-size: 0.88rem;
      background: rgba(255,255,255,0.78);
    }}

    .tag.new {{
      background: var(--new-soft);
      border-color: rgba(28, 124, 84, 0.2);
      color: var(--new);
    }}

    .tag.warn {{
      background: var(--warn-soft);
      border-color: rgba(183, 110, 0, 0.2);
      color: var(--warn);
    }}

    .tag.danger {{
      background: var(--danger-soft);
      border-color: rgba(157, 42, 42, 0.2);
      color: var(--danger);
    }}

    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px 14px;
      margin-bottom: 14px;
      color: var(--muted);
      font-size: 0.95rem;
    }}

    .grid strong {{
      display: block;
      margin-bottom: 4px;
      color: var(--text);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}

    .summary {{
      margin: 0 0 12px;
      line-height: 1.58;
      color: #243447;
    }}

    .reason {{
      margin: 0;
      padding: 12px 14px;
      border-radius: 14px;
      background: var(--accent-soft);
      color: #184078;
      font-size: 0.96rem;
    }}

    .keyword-details {{
      margin: 0 0 14px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255,255,255,0.7);
      box-shadow: var(--shadow-soft);
      overflow: hidden;
    }}

    .keyword-details summary {{
      cursor: pointer;
      list-style: none;
      padding: 12px 14px;
      font-weight: 600;
      color: var(--accent-deep);
    }}

    .keyword-details summary::-webkit-details-marker {{
      display: none;
    }}

    .keyword-tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 0 14px 14px;
    }}

    .keyword-chip {{
      display: inline-flex;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(18, 96, 255, 0.08);
      border: 1px solid rgba(18, 96, 255, 0.12);
      color: var(--accent-deep);
      font-size: 0.86rem;
    }}

    .keyword-chip.actionable {{
      cursor: pointer;
      user-select: none;
      transition: transform 120ms ease, box-shadow 120ms ease, background 120ms ease;
    }}

    .keyword-chip.actionable:hover {{
      transform: translateY(-1px);
      box-shadow: var(--shadow-soft);
      background: rgba(18, 96, 255, 0.13);
    }}

    .edit-details {{
      margin: 0 0 14px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255,255,255,0.78);
      box-shadow: var(--shadow-soft);
      overflow: hidden;
    }}

    .edit-details summary {{
      cursor: pointer;
      list-style: none;
      padding: 12px 14px;
      font-weight: 600;
      color: var(--accent-deep);
    }}

    .edit-details summary::-webkit-details-marker {{
      display: none;
    }}

    .edit-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      padding: 0 14px 14px;
    }}

    .edit-field {{
      display: grid;
      gap: 8px;
      padding: 12px;
      border: 1px solid rgba(138, 160, 187, 0.18);
      border-radius: 14px;
      background: rgba(248, 251, 253, 0.86);
    }}

    .edit-field.full {{
      grid-column: 1 / -1;
    }}

    .edit-field-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }}

    .edit-field-head strong {{
      font-size: 0.88rem;
      letter-spacing: 0.02em;
    }}

    .edit-input,
    .edit-textarea {{
      width: 100%;
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid rgba(138, 160, 187, 0.28);
      background: rgba(255,255,255,0.94);
      color: var(--text);
      font: inherit;
      box-shadow: var(--shadow-soft);
    }}

    .edit-textarea {{
      min-height: 92px;
      resize: vertical;
    }}

    .edit-input:focus,
    .edit-textarea:focus {{
      outline: none;
      border-color: rgba(18, 96, 255, 0.35);
      box-shadow: 0 0 0 4px rgba(18, 96, 255, 0.08);
    }}

    .edit-actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}

    .button.small {{
      min-height: 38px;
      padding: 8px 12px;
      font-size: 0.84rem;
    }}

    .override-badge {{
      display: inline-flex;
      align-items: center;
      padding: 4px 8px;
      border-radius: 999px;
      background: rgba(18, 96, 255, 0.1);
      border: 1px solid rgba(18, 96, 255, 0.16);
      color: var(--accent-deep);
      font-size: 0.75rem;
      font-weight: 700;
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }}

    .original-value,
    .field-note {{
      color: var(--muted);
      font-size: 0.82rem;
      line-height: 1.45;
    }}

    .section-label {{
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-weight: 600;
    }}

    .empty {{
      padding: 28px;
      border-radius: var(--radius-lg);
      background: rgba(255,255,255,0.72);
      border: 1px dashed var(--line);
      color: var(--muted);
      text-align: center;
      box-shadow: var(--shadow-soft);
    }}

    .toast {{
      position: fixed;
      top: 20px;
      right: 20px;
      z-index: 1000;
      padding: 12px 16px;
      border-radius: 14px;
      background: rgba(16, 32, 51, 0.92);
      color: #fff;
      box-shadow: var(--shadow);
      opacity: 0;
      transform: translateY(-10px);
      transition: opacity 0.18s ease, transform 0.18s ease;
      pointer-events: none;
      font-size: 0.92rem;
    }}

    .update-banner {{
      position: sticky;
      top: 14px;
      z-index: 900;
      margin: 16px 0 0;
      padding: 12px 14px;
      border-radius: 14px;
      background: rgba(18, 96, 255, 0.1);
      border: 1px solid rgba(18, 96, 255, 0.16);
      color: var(--accent-deep);
      display: none;
      box-shadow: var(--shadow-soft);
    }}

    .update-banner.visible {{
      display: block;
    }}

    .update-banner.error {{
      background: rgba(194, 54, 69, 0.1);
      border-color: rgba(194, 54, 69, 0.18);
      color: var(--danger);
    }}

    .toast.visible {{
      opacity: 1;
      transform: translateY(0);
    }}

    .toast.error {{
      background: rgba(194, 54, 69, 0.95);
    }}

    @media (max-width: 980px) {{
      .layout {{
        grid-template-columns: 1fr;
      }}
      .sidebar {{
        position: static;
        max-height: none;
        overflow: visible;
        padding-right: 0;
      }}
      .controls {{
        grid-template-columns: 1fr;
      }}
      .settings-grid {{
        grid-template-columns: 1fr;
      }}
      .presets,
      .toolbar {{
        grid-template-columns: 1fr 1fr;
      }}
      .focus-panels {{
        grid-template-columns: 1fr;
      }}
    }}

    @media (max-width: 640px) {{
      .controls {{
        grid-template-columns: 1fr;
      }}
      .presets,
      .toolbar {{
        grid-template-columns: 1fr;
      }}
      .card-header {{
        grid-template-columns: 1fr;
      }}
      .actions {{
        justify-content: flex-start;
      }}
      .wrap {{
        padding: 18px 14px 48px;
      }}
      .hero {{
        padding: 22px 18px;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div>
        <p>Academic discovery dashboard</p>
        <h1>Jobs and fellowships in one view</h1>
      </div>
      <p>Generated on {escape(today.isoformat())}. This page shows the current matched opportunities, highlights what is new, and lets you quickly search, filter, and sort without opening spreadsheets.</p>
      <div class="server-indicator" id="serverIndicator"><span class="server-dot"></span><span id="serverIndicatorText">Checking server connection...</span></div>
      <div class="stats">
        <div class="stat"><strong>{len(jobs)}</strong><span>Jobs</span><small>Current dataset</small></div>
        <div class="stat"><strong>{len(fellowships)}</strong><span>Fellowships</span><small>Current dataset</small></div>
        <div class="stat"><strong>{sum(1 for item in jobs if item.get("url") not in previous_jobs)}</strong><span>New jobs</span><small>Since last run</small></div>
        <div class="stat"><strong>{sum(1 for item in fellowships if item.get("url") not in previous_fellowships)}</strong><span>New fellowships</span><small>Since last run</small></div>
        <div class="stat"><strong id="heroInterestedCount">{interested_count}</strong><span>Interested</span><small>Status total</small></div>
        <div class="stat"><strong id="heroAppliedCount">{applied_count}</strong><span>Applied</span><small>Status total</small></div>
        <div class="stat"><strong id="heroIgnoredCount">{ignored_count}</strong><span>Ignored</span><small>Status total</small></div>
      </div>
    </section>
    <div id="sessionWarning" class="update-banner"></div>
    <div id="updateBanner" class="update-banner"></div>
    <div class="layout">
      <aside class="sidebar">
        <section class="sidebar-panel">
          <h3>Filters</h3>
          <p>Search, sort, and narrow the list without scrolling back to the top.</p>
          <section class="sidebar-group">
            <p class="sidebar-label">Search</p>
            <section class="controls">
              <input id="search" type="text" placeholder="Search title, institution, summary, methods...">
              <button class="button secondary" id="clearKeywordFilter" type="button">Clear keyword filter</button>
            </section>
          </section>
          <section class="sidebar-group">
            <p class="sidebar-label">Filters</p>
            <section class="controls">
              <select id="typeFilter">
                <option value="all">All types</option>
                <option value="job">Jobs only</option>
                <option value="fellowship">Fellowships only</option>
              </select>
              <select id="newFilter">
                <option value="all">All results</option>
                <option value="new">New only</option>
              </select>
              <select id="deadlineFilter">
                <option value="all">Any deadline</option>
                <option value="7">Within 7 days</option>
                <option value="14">Within 14 days</option>
                <option value="30">Within 30 days</option>
              </select>
              <select id="sortBy">
                <option value="deadline_asc" selected>Sort by earliest deadline</option>
                <option value="deadline_desc">Sort by latest deadline</option>
                <option value="score">Sort by match score</option>
                <option value="new">Sort by new first</option>
                <option value="title">Sort by title</option>
              </select>
              <select id="sourceFilter">
                <option value="all">All source sites</option>
              </select>
              <select id="countryFilter">
                <option value="all">All countries</option>
              </select>
              <select id="institutionFilter">
                <option value="all">All institutions</option>
              </select>
            </section>
          </section>
          <section class="sidebar-group">
            <p class="sidebar-label">Views</p>
            <section class="presets">
              <button class="preset active" data-preset="all" type="button">All</button>
              <button class="preset" data-preset="uk" type="button">UK focus</button>
              <button class="preset" data-preset="europe" type="button">Europe focus</button>
              <button class="preset" data-preset="fellowships" type="button">Fellowships</button>
              <button class="preset" data-preset="urgent" type="button">Urgent deadlines</button>
            </section>
          </section>
          <section class="sidebar-group">
            <p class="sidebar-label">Quick toggles</p>
            <p class="sidebar-note">Use these as the only shortcut filters. The cards above are summary only.</p>
            <section class="toolbar">
              <button class="toggle" id="toggleAllStatuses" type="button">All statuses</button>
              <button class="toggle" id="toggleUnprocessed" type="button">Unprocessed</button>
              <button class="toggle" id="toggleInterested" type="button">Interested</button>
              <button class="toggle" id="toggleApplied" type="button">Applied</button>
              <button class="toggle" id="toggleIgnored" type="button">Ignored</button>
              <button class="toggle" id="toggleNew" type="button">New only</button>
              <button class="toggle" id="toggleUrgent" type="button">Deadline within 7 days</button>
              <button class="toggle" id="toggleHighMatch" type="button">High match only</button>
            </section>
          </section>
        </section>

        <section class="sidebar-panel settings-panel">
          <div class="settings-head">
            <div>
              <h3>Match Settings</h3>
              <p>Edit keywords and exclude terms directly here, then save and refresh.</p>
            </div>
          </div>
      <div class="settings-grid">
            <div class="settings-field">
              <label for="keywordsEditor">Keywords</label>
              <textarea id="keywordsEditor" placeholder="One keyword per line"></textarea>
            </div>
            <div class="settings-field">
              <label for="excludeTermsEditor">Exclude terms</label>
              <textarea id="excludeTermsEditor" placeholder="One exclude term per line"></textarea>
            </div>
            <div class="settings-field">
              <label for="protectedTermsEditor">Protected terms</label>
              <textarea id="protectedTermsEditor" placeholder="One protected term per line"></textarea>
            </div>
            <div class="settings-field">
              <label for="expandedTermsEditor">Expanded terms</label>
              <textarea id="expandedTermsEditor" placeholder="One expanded term per line"></textarea>
            </div>
          </div>
          <div class="settings-actions">
            <button class="button" id="saveConfigButton" type="button">Save settings</button>
            <button class="button secondary" id="saveRefreshButton" type="button">Save and refresh data</button>
            <button class="button secondary" id="restoreStatusesButton" type="button">Restore statuses</button>
            <button class="button secondary" id="undoStatusButton" type="button">Undo last status</button>
            <span class="settings-note" id="settingsNote">Changes are written to config.json.</span>
          </div>
          <div class="settings-note" id="systemStateNote">Loading local data status...</div>
          <div class="source-health" id="sourceHealthPanel">
            <div class="settings-head compact">
              <div>
                <h3>Source Health</h3>
                <p>Latest fetch status per source.</p>
              </div>
            </div>
            <div class="source-health-list" id="sourceHealthList">
              <div class="settings-note">Loading source diagnostics...</div>
            </div>
          </div>
        </section>
      </aside>

      <main class="main-column">
        <section class="summary-strip" id="summaryStrip"></section>
        <section class="priority">
          <div class="priority-head">
            <h3>Priority Today</h3>
            <span id="priorityCaption">Best next opportunities to review first.</span>
          </div>
          <div class="priority-grid" id="priorityGrid"></div>
        </section>

        <section class="focus-panels">
          <section class="focus-panel">
            <div class="priority-head">
              <h3>Interested Queue</h3>
              <a class="button secondary" href="dashboard.html?view=interested">Open queue</a>
            </div>
            <div class="focus-list" id="interestedList">{interested_focus_html}</div>
          </section>
          <section class="focus-panel">
            <div class="priority-head">
              <h3>Applied Tracker</h3>
              <a class="button secondary" href="dashboard.html?view=applied">Open tracker</a>
            </div>
            <div class="focus-list" id="appliedList">{applied_focus_html}</div>
          </section>
        </section>

        <section id="results" class="results">{initial_results_html}</section>
      </main>
    </div>
  </div>
  <div id="toast" class="toast"></div>

  <script>
    const bootstrapData = {payload};
    const bootstrapConfig = {config_payload};
    let data = bootstrapData;
    const resultsEl = document.getElementById("results");
    const searchEl = document.getElementById("search");
    const clearKeywordFilterEl = document.getElementById("clearKeywordFilter");
    const typeFilterEl = document.getElementById("typeFilter");
    const newFilterEl = document.getElementById("newFilter");
    const deadlineFilterEl = document.getElementById("deadlineFilter");
    const sortByEl = document.getElementById("sortBy");
    const sourceFilterEl = document.getElementById("sourceFilter");
    const countryFilterEl = document.getElementById("countryFilter");
    const institutionFilterEl = document.getElementById("institutionFilter");
    const toggleNewEl = document.getElementById("toggleNew");
    const toggleUrgentEl = document.getElementById("toggleUrgent");
    const toggleHighMatchEl = document.getElementById("toggleHighMatch");
    const toggleAllStatusesEl = document.getElementById("toggleAllStatuses");
    const toggleUnprocessedEl = document.getElementById("toggleUnprocessed");
    const toggleInterestedEl = document.getElementById("toggleInterested");
    const toggleAppliedEl = document.getElementById("toggleApplied");
    const toggleIgnoredEl = document.getElementById("toggleIgnored");
    const summaryStripEl = document.getElementById("summaryStrip");
    const priorityGridEl = document.getElementById("priorityGrid");
    const priorityCaptionEl = document.getElementById("priorityCaption");
    const interestedListEl = document.getElementById("interestedList");
    const appliedListEl = document.getElementById("appliedList");
    const presetButtons = [...document.querySelectorAll(".preset")];
    const heroInterestedCountEl = document.getElementById("heroInterestedCount");
    const heroAppliedCountEl = document.getElementById("heroAppliedCount");
    const heroIgnoredCountEl = document.getElementById("heroIgnoredCount");
    const toastEl = document.getElementById("toast");
    const sessionWarningEl = document.getElementById("sessionWarning");
    const updateBannerEl = document.getElementById("updateBanner");
    const serverIndicatorEl = document.getElementById("serverIndicator");
    const serverIndicatorTextEl = document.getElementById("serverIndicatorText");
    serverIndicatorEl.classList.add("js-active");
    serverIndicatorTextEl.textContent = "JS active, checking server...";
    const keywordsEditorEl = document.getElementById("keywordsEditor");
    const excludeTermsEditorEl = document.getElementById("excludeTermsEditor");
    const protectedTermsEditorEl = document.getElementById("protectedTermsEditor");
    const expandedTermsEditorEl = document.getElementById("expandedTermsEditor");
    const saveConfigButtonEl = document.getElementById("saveConfigButton");
    const saveRefreshButtonEl = document.getElementById("saveRefreshButton");
    const restoreStatusesButtonEl = document.getElementById("restoreStatusesButton");
    const undoStatusButtonEl = document.getElementById("undoStatusButton");
    const settingsNoteEl = document.getElementById("settingsNote");
    const systemStateNoteEl = document.getElementById("systemStateNote");
    const sourceHealthListEl = document.getElementById("sourceHealthList");
    let saveError = "";
    let toastTimer = null;
    let updatePollTimer = null;
    const query = new URLSearchParams(window.location.search);
    const initialView = query.get("view");

    const quickState = {{
      newOnly: false,
      urgentOnly: false,
      highMatchOnly: false,
      showIgnored: false,
      preset: "all",
      statusView: "unprocessed",
    }};

    function setStatusView(view) {{
      quickState.statusView = view;
    }}

    populateSelect(sourceFilterEl, uniqueValues("source_site"), "All source sites");
    populateSelect(countryFilterEl, uniqueValues("country"), "All countries");
    populateSelect(institutionFilterEl, uniqueValues("institution"), "All institutions");

    if (initialView === "interested" || initialView === "applied") {{
      setStatusView(initialView);
    }}

    function safe(value) {{
      return value === null || value === undefined || value === "" ? "N/A" : String(value);
    }}

    function attr(value) {{
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }}

    function overrideFields(item) {{
      return new Set(
        String(item.manual_override_fields || "")
          .split(",")
          .map(term => term.trim())
          .filter(Boolean)
      );
    }}

    function originalFieldKey(field) {{
      if (field === "title") return "original_title";
      if (field === "institution") return "original_institution";
      if (field === "posted_date") return "original_posted_date";
      if (field === "application_deadline") return "original_application_deadline";
      if (field === "note") return "original_note";
      return "";
    }}

    function fieldLabel(field) {{
      if (field === "application_deadline") return "Deadline";
      if (field === "posted_date") return "Posted";
      if (field === "institution") return "Institution";
      if (field === "title") return "Title";
      if (field === "note") return "My note";
      return field;
    }}

    function hasManualOverride(item, field) {{
      return overrideFields(item).has(field);
    }}

    function originalValue(item, field) {{
      const key = originalFieldKey(field);
      return key ? String(item[key] || "") : "";
    }}

    function setManualOverrideState(item, field, value) {{
      const fields = overrideFields(item);
      const originalKey = originalFieldKey(field);
      if (originalKey && item[originalKey] === undefined) {{
        item[originalKey] = item[field] || "";
      }}
      item[field] = value;
      fields.add(field);
      item.manual_override_fields = [...fields].join(", ");
      item.has_manual_overrides = fields.size > 0;
      item.manual_overrides_updated_at = new Date().toISOString();
    }}

    function clearManualOverrideState(item, field) {{
      const fields = overrideFields(item);
      const originalKey = originalFieldKey(field);
      item[field] = originalKey ? String(item[originalKey] || "") : "";
      fields.delete(field);
      item.manual_override_fields = [...fields].join(", ");
      item.has_manual_overrides = fields.size > 0;
      if (!fields.size) {{
        item.manual_overrides_updated_at = "";
      }}
    }}

    function originalValueMarkup(item, field) {{
      if (!hasManualOverride(item, field)) {{
        return "";
      }}
      const original = originalValue(item, field);
      return `<div class="original-value">Original value: ${{attr(original || "empty")}}</div>`;
    }}

    function editFieldMarkup(item, field, options = {{}}) {{
      const value = String(item[field] || "");
      const isNote = field === "note";
      const edited = hasManualOverride(item, field);
      const input = isNote
        ? `<textarea class="edit-textarea" data-edit-input="${{field}}" data-url="${{attr(item.url)}}">${{attr(value)}}</textarea>`
        : `<input class="edit-input" data-edit-input="${{field}}" data-url="${{attr(item.url)}}" type="${{options.type || "text"}}" value="${{attr(value)}}" placeholder="${{attr(options.placeholder || "")}}">`;
      return `
        <div class="edit-field ${{isNote ? "full" : ""}}" data-edit-field="${{field}}" data-url="${{attr(item.url)}}">
          <div class="edit-field-head">
            <strong>${{fieldLabel(field)}}</strong>
            ${{edited ? '<span class="override-badge">Manually edited</span>' : ""}}
          </div>
          ${{input}}
          ${{originalValueMarkup(item, field)}}
          <div class="edit-actions">
            <button class="button small secondary" type="button" data-save-field="${{field}}" data-url="${{attr(item.url)}}">Save</button>
            <button class="button small secondary" type="button" data-reset-field="${{field}}" data-url="${{attr(item.url)}}" ${{edited ? "" : "disabled"}}>Reset field</button>
          </div>
        </div>
      `;
    }}

    function splitTerms(text) {{
      return text
        .split(/[\\n,]+/)
        .map(item => item.trim())
        .filter(Boolean)
        .filter((item, index, items) => items.findIndex(other => other.toLowerCase() === item.toLowerCase()) === index);
    }}

    function renderSourceHealth(items) {{
      if (!sourceHealthListEl) {{
        return;
      }}
      if (!Array.isArray(items) || !items.length) {{
        sourceHealthListEl.innerHTML = '<div class="settings-note">No source diagnostics available yet.</div>';
        return;
      }}
      sourceHealthListEl.innerHTML = items.map(item => {{
        const statusValue = String(item.status || "");
        const errorState = ["fetch_failed", "cache_fallback_after_error"].includes(statusValue);
        const modeBits = [
          item.dynamic_source ? "dynamic" : "static",
          item.fetch_mode ? `mode=${{safe(item.fetch_mode)}}` : "",
          item.fallback_used ? "fallback" : ""
        ].filter(Boolean).join(" | ");
        const healthBits = [
          `items=${{safe(item.items_count)}}`,
          `filtered=${{safe(item.filtered_count)}}`,
          `cache=${{item.cache_hit ? "hit" : "miss"}}`,
          `detail ok=${{safe(item.detail_success)}}`,
          `detail fail=${{safe(item.detail_failed)}}`,
          item.parser_failures ? `parser fail=${{safe(item.parser_failures)}}` : "",
          item.consecutive_failures ? `fail streak=${{safe(item.consecutive_failures)}}` : "",
          item.last_success_at ? `last success=${{safe(item.last_success_at)}}` : ""
        ].filter(Boolean).join(" | ");
        const errorText = item.error ? `<div class="source-health-meta">${{safe(item.error)}}</div>` : "";
        return `<div class="source-health-item ${{errorState ? "error" : ""}}">
          <strong>${{safe(item.source_name || item.source_key)}}</strong>
          <div class="source-health-meta">key=${{safe(item.source_key)}} | status=${{safe(statusValue)}}${{modeBits ? ` | ${{modeBits}}` : ""}}</div>
          <div class="source-health-meta">${{healthBits}}</div>
          ${{errorText}}
        </div>`;
      }}).join("");
    }}

    function syncKeywordClearButton() {{
      clearKeywordFilterEl.disabled = !searchEl.value.trim();
    }}

    function getStatus(url) {{
      const item = data.find(row => row.url === url);
      return item && item.status ? item.status : "";
    }}

    async function setStatus(url, status) {{
      const normalized = status === "none" ? "" : status;
      try {{
        const response = await fetch("/api/status", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ url, status: normalized }})
        }});
        if (!response.ok) {{
          throw new Error("Status save failed");
        }}
        data.forEach(item => {{
          if (item.url === url) item.status = normalized;
        }});
        saveError = "";
        showToast(normalized ? `Saved: ${{normalized}}` : "Status cleared");
        render();
      }} catch (error) {{
        saveError = "Status could not be written to the runtime database. Open the dashboard through the local server.";
        showToast("Save failed", true);
        render();
      }}
    }}

    async function parseApiError(response, fallbackMessage) {{
      try {{
        const payload = await response.json();
        return payload.detail || payload.message || fallbackMessage;
      }} catch (_error) {{
        return fallbackMessage;
      }}
    }}

    async function saveOpportunityNote(url, value) {{
      try {{
        const response = await fetch("/api/opportunity-note", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ url, field: "note", value }})
        }});
        if (!response.ok) {{
          throw new Error(await parseApiError(response, "Note save failed"));
        }}
        data.forEach(item => {{
          if (item.url === url) {{
            setManualOverrideState(item, "note", value);
          }}
        }});
        showToast("Note saved");
        render();
      }} catch (error) {{
        showToast(error.message || "Note save failed", true);
      }}
    }}

    async function saveOpportunityOverride(url, field, value) {{
      try {{
        const response = await fetch("/api/opportunity-override", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ url, field, value }})
        }});
        if (!response.ok) {{
          throw new Error(await parseApiError(response, "Field save failed"));
        }}
        data.forEach(item => {{
          if (item.url === url) {{
            setManualOverrideState(item, field, value);
          }}
        }});
        showToast(`${{fieldLabel(field)}} saved`);
        render();
      }} catch (error) {{
        showToast(error.message || "Field save failed", true);
      }}
    }}

    async function resetOpportunityOverride(url, field) {{
      try {{
        const response = await fetch("/api/opportunity-override/reset", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ url, field }})
        }});
        if (!response.ok) {{
          throw new Error(await parseApiError(response, "Reset failed"));
        }}
        data.forEach(item => {{
          if (item.url === url) {{
            clearManualOverrideState(item, field);
          }}
        }});
        showToast(`${{fieldLabel(field)}} reset`);
        render();
      }} catch (error) {{
        showToast(error.message || "Reset failed", true);
      }}
    }}

    function showToast(message, isError = false) {{
      toastEl.textContent = message;
      toastEl.classList.toggle("error", isError);
      toastEl.classList.add("visible");
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(() => {{
        toastEl.classList.remove("visible");
      }}, 2200);
    }}

    function showUpdateBanner(message, isError = false) {{
      updateBannerEl.textContent = message;
      updateBannerEl.classList.toggle("error", isError);
      updateBannerEl.classList.add("visible");
    }}

    function hideUpdateBanner() {{
      updateBannerEl.classList.remove("visible");
      updateBannerEl.classList.remove("error");
      updateBannerEl.textContent = "";
    }}

    function showSessionWarning(message) {{
      if (!message) {{
        sessionWarningEl.classList.remove("visible");
        sessionWarningEl.classList.remove("error");
        sessionWarningEl.textContent = "";
        return;
      }}
      sessionWarningEl.textContent = message;
      sessionWarningEl.classList.add("visible");
      sessionWarningEl.classList.add("error");
    }}

    function uniqueValues(field) {{
      return [...new Set(data.map(item => String(item[field] || "").trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    }}

    function populateSelect(select, values, label) {{
      select.innerHTML = `<option value="all">${{label}}</option>` +
        values.map(value => `<option value="${{value}}">${{value}}</option>`).join("");
    }}

    function syncQuickToggleButtons() {{
      toggleNewEl.classList.toggle("active", quickState.newOnly);
      toggleUrgentEl.classList.toggle("active", quickState.urgentOnly);
      toggleHighMatchEl.classList.toggle("active", quickState.highMatchOnly);
      toggleAllStatusesEl.classList.toggle("active", quickState.statusView === "all");
      toggleUnprocessedEl.classList.toggle("active", quickState.statusView === "unprocessed");
      toggleInterestedEl.classList.toggle("active", quickState.statusView === "interested");
      toggleAppliedEl.classList.toggle("active", quickState.statusView === "applied");
      toggleIgnoredEl.classList.toggle("active", quickState.statusView === "ignored");
    }}

    function renderHeroStatusCounts() {{
      const interestedCount = data.filter(item => getStatus(item.url) === "interested").length;
      const appliedCount = data.filter(item => getStatus(item.url) === "applied").length;
      const ignoredCount = data.filter(item => getStatus(item.url) === "ignored").length;
      heroInterestedCountEl.textContent = String(interestedCount);
      heroAppliedCountEl.textContent = String(appliedCount);
      heroIgnoredCountEl.textContent = String(ignoredCount);
    }}

    async function loadConfigEditor() {{
      keywordsEditorEl.value = (bootstrapConfig.keywords || []).join("\\n");
      excludeTermsEditorEl.value = (bootstrapConfig.exclude_terms || []).join("\\n");
      protectedTermsEditorEl.value = (bootstrapConfig.protected_terms || []).join("\\n");
      expandedTermsEditorEl.value = (bootstrapConfig.expanded_terms || []).join("\\n");

      if (!window.location.protocol.startsWith("http")) {{
        settingsNoteEl.textContent = "Viewing saved config only. Open through start_dashboard.bat to edit and save.";
        return;
      }}
      try {{
        const response = await fetch("/api/config");
        if (!response.ok) throw new Error("fetch failed");
        const payload = await response.json();
        if (!payload.ok || !payload.config) throw new Error("config failed");
        keywordsEditorEl.value = (payload.config.keywords || []).join("\\n");
        excludeTermsEditorEl.value = (payload.config.exclude_terms || []).join("\\n");
        protectedTermsEditorEl.value = (payload.config.protected_terms || []).join("\\n");
        expandedTermsEditorEl.value = (payload.config.expanded_terms || []).join("\\n");
        settingsNoteEl.textContent = "Changes are written to config.json.";
      }} catch (error) {{
        settingsNoteEl.textContent = "Could not load config from the server. Open through start_dashboard.bat.";
      }}
    }}

    async function startRefresh() {{
      if (!window.location.protocol.startsWith("http")) {{
        return;
      }}
      try {{
        const response = await fetch("/api/refresh", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{}})
        }});
        if (!response.ok) throw new Error("refresh failed");
        const payload = await response.json();
        if (payload.started) {{
          showUpdateBanner("Refreshing opportunities in the background...");
          showToast("Refresh started");
        }} else {{
          showToast(payload.message || "Refresh already running");
        }}
      }} catch (error) {{
        showToast("Could not start refresh", true);
      }}
    }}

    async function saveConfig(refreshAfterSave = false) {{
      if (!window.location.protocol.startsWith("http")) {{
        settingsNoteEl.textContent = "Open through start_dashboard.bat to edit and save.";
        showToast("Open through start_dashboard.bat to edit config", true);
        return;
      }}
      const payload = {{
        keywords: splitTerms(keywordsEditorEl.value),
        exclude_terms: splitTerms(excludeTermsEditorEl.value),
        protected_terms: splitTerms(protectedTermsEditorEl.value),
        expanded_terms: splitTerms(expandedTermsEditorEl.value),
      }};
      try {{
        saveConfigButtonEl.disabled = true;
        saveRefreshButtonEl.disabled = true;
        const response = await fetch("/api/config", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload)
        }});
        if (!response.ok) throw new Error("save failed");
        settingsNoteEl.textContent = "Saved to config.json.";
        showToast("Settings saved");
        if (refreshAfterSave) {{
          await startRefresh();
        }}
      }} catch (error) {{
        settingsNoteEl.textContent = "Could not save config. Open through start_dashboard.bat.";
        showToast("Config save failed. Use the local server.", true);
      }} finally {{
        saveConfigButtonEl.disabled = false;
        saveRefreshButtonEl.disabled = false;
      }}
    }}

    async function restoreStatuses() {{
      if (!window.location.protocol.startsWith("http")) {{
        showToast("Open through the local server to restore statuses", true);
        return;
      }}
      try {{
        restoreStatusesButtonEl.disabled = true;
        const response = await fetch("/api/restore-statuses", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{}})
        }});
        if (!response.ok) throw new Error("restore failed");
        const payload = await response.json();
        await hydrateData();
        showToast(`Restored ${{payload.restored || 0}} statuses`);
      }} catch (error) {{
        showToast("Could not restore statuses", true);
      }} finally {{
        restoreStatusesButtonEl.disabled = false;
      }}
    }}

    async function undoLastStatus() {{
      if (!window.location.protocol.startsWith("http")) {{
        showToast("Open through the local server to undo status changes", true);
        return;
      }}
      try {{
        undoStatusButtonEl.disabled = true;
        const response = await fetch("/api/undo-status", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{}})
        }});
        if (!response.ok) throw new Error("undo failed");
        const payload = await response.json();
        if (!payload.ok || !payload.undone) {{
          showToast(payload.message || "Nothing to undo", true);
          return;
        }}
        await hydrateData();
        showToast(`Undo complete: ${{payload.previous_status || "clear"}} -> ${{payload.restored_status || "clear"}}`);
      }} catch (error) {{
        showToast("Could not undo last status action", true);
      }} finally {{
        undoStatusButtonEl.disabled = false;
      }}
    }}

    function card(item) {{
      const tags = [];
      tags.push(`<span class="tag">${{safe(item.type)}}</span>`);
      tags.push(`<span class="tag">score ${{safe(item.match_score)}}</span>`);
      if (item.source_site) tags.push(`<span class="tag">${{safe(item.source_site)}}</span>`);
      if (item.is_new) tags.push('<span class="tag new">new</span>');
      const status = getStatus(item.url);
      if (status === "interested") tags.push('<span class="tag">interested</span>');
      if (status === "applied") tags.push('<span class="tag new">applied</span>');
      if (status === "ignored") tags.push('<span class="tag">ignored</span>');
      if (typeof item.days_left === "number" && item.days_left <= 7 && item.days_left >= 0) {{
        tags.push(`<span class="tag danger">${{item.days_left}} days left</span>`);
      }} else if (typeof item.days_left === "number" && item.days_left <= 30 && item.days_left >= 0) {{
        tags.push(`<span class="tag warn">${{item.days_left}} days left</span>`);
      }}

        const matchedKeywords = String(item.matched_keywords || "")
          .split(",")
          .map(term => term.trim())
          .filter(Boolean);
        const keywordBlock = matchedKeywords.length
        ? `
          <details class="keyword-details">
            <summary>Matched keywords (${{matchedKeywords.length}})</summary>
            <div class="keyword-tags">
              ${{matchedKeywords.map(term => `<span class="keyword-chip actionable" data-keyword-filter="${{safe(term)}}">${{safe(term)}}</span>`).join("")}}
            </div>
          </details>
        `
        : "";
      const editBlock = `
        <details class="edit-details">
          <summary>Edit details</summary>
          <div class="edit-grid">
            ${{editFieldMarkup(item, "note")}}
            ${{editFieldMarkup(item, "application_deadline", {{ type: "date", placeholder: "YYYY-MM-DD" }})}}
            ${{editFieldMarkup(item, "posted_date", {{ type: "date", placeholder: "YYYY-MM-DD" }})}}
            ${{editFieldMarkup(item, "title", {{ placeholder: "Override title" }})}}
            ${{editFieldMarkup(item, "institution", {{ placeholder: "Override institution" }})}}
          </div>
        </details>
      `;

      return `
        <article class="card">
          <div class="card-header">
            <div>
              <h2><a href="${{item.url}}" target="_blank" rel="noreferrer">${{safe(item.title)}}</a></h2>
              <div class="meta">${{tags.join("")}}</div>
            </div>
            <div class="actions">
              <a class="button" href="${{item.url}}" target="_blank" rel="noreferrer">Open Original Listing</a>
              <a class="button secondary" href="${{item.url}}" target="_blank" rel="noreferrer">Source Page</a>
            </div>
          </div>
          <div class="grid">
            <div><strong>Institution</strong>${{safe(item.institution)}}</div>
            <div><strong>Department</strong>${{safe(item.department)}}</div>
            <div><strong>Location</strong>${{safe(item.location)}}</div>
            <div><strong>Country</strong>${{safe(item.country)}}</div>
            <div><strong>Salary</strong>${{safe(item.salary)}}</div>
            <div><strong>Posted</strong>${{safe(item.posted_date)}}</div>
            <div><strong>Deadline</strong>${{safe(item.application_deadline || item.deadline_status)}}</div>
            <div><strong>Source</strong>${{safe(item.source_site)}}</div>
          </div>
          <div class="status-row">
            <button class="status-btn ${{status === "interested" ? "active" : ""}}" data-status="interested" data-url="${{item.url}}">Interested</button>
            <button class="status-btn ${{status === "applied" ? "active" : ""}}" data-status="applied" data-url="${{item.url}}">Applied</button>
            <button class="status-btn ${{status === "ignored" ? "active" : ""}}" data-status="ignored" data-url="${{item.url}}">Ignore</button>
            <button class="status-btn ${{!status ? "active" : ""}}" data-status="none" data-url="${{item.url}}">Clear</button>
          </div>
          ${{keywordBlock}}
          ${{editBlock}}
          <p class="section-label">Opportunity Summary</p>
          <p class="summary">${{safe(item.summary)}}</p>
          <p class="section-label">Why It Matches</p>
          <div class="reason">${{safe(item.match_reason)}}</div>
        </article>
      `;
    }}

    function priorityCard(item) {{
      return `
        <article class="priority-card">
          <a href="${{item.url}}" target="_blank" rel="noreferrer">${{safe(item.title)}}</a>
          <p>${{safe(item.institution)}} · ${{safe(item.application_deadline || item.deadline_status)}} · score ${{safe(item.match_score)}}</p>
        </article>
      `;
    }}

    function focusItem(item) {{
      return `
        <article class="focus-item">
          <a href="${{item.url}}" target="_blank" rel="noreferrer">${{safe(item.title)}}</a>
          <p>${{safe(item.institution)}} · ${{safe(item.application_deadline || item.deadline_status)}} · score ${{safe(item.match_score)}}</p>
        </article>
      `;
    }}

    function matchesSearch(item, term) {{
      if (!term) return true;
      const haystack = [
        item.title, item.institution, item.department, item.location, item.country,
        item.summary, item.eligibility, item.match_reason
      ].join(" ").toLowerCase();
      return haystack.includes(term);
    }}

    function matchesDeadline(item, limit) {{
      if (limit === "all") return true;
      if (typeof item.days_left !== "number") return false;
      return item.days_left >= 0 && item.days_left <= Number(limit);
    }}

    function matchesCountry(item, country) {{
      return country === "all" ? true : safe(item.country) === country;
    }}

    function matchesInstitution(item, institution) {{
      return institution === "all" ? true : safe(item.institution) === institution;
    }}

    function matchesSource(item, source) {{
      return source === "all" ? true : safe(item.source_site) === source;
    }}

    function deadlineRank(item) {{
      if (typeof item.days_left !== "number") return 999999;
      if (item.days_left < 0) return 800000 + Math.abs(item.days_left);
      return item.days_left;
    }}

    function compare(a, b, sortBy) {{
      if (sortBy === "deadline_asc") {{
        return deadlineRank(a) - deadlineRank(b) || Number(b.match_score || 0) - Number(a.match_score || 0);
      }}
      if (sortBy === "deadline_desc") {{
        return deadlineRank(b) - deadlineRank(a) || Number(b.match_score || 0) - Number(a.match_score || 0);
      }}
      if (sortBy === "new") {{
        return Number(b.is_new) - Number(a.is_new) || Number(b.match_score || 0) - Number(a.match_score || 0);
      }}
      if (sortBy === "title") {{
        return String(a.title || "").localeCompare(String(b.title || ""));
      }}
      return Number(b.match_score || 0) - Number(a.match_score || 0);
    }}

    function applyPreset(item) {{
      if (quickState.preset === "all") return true;
      if (quickState.preset === "uk") return safe(item.country).toLowerCase().includes("united kingdom");
      if (quickState.preset === "europe") {{
        const blocked = ["china", "japan", "singapore", "united states", "usa", "canada", "australia"];
        const country = safe(item.country).toLowerCase();
        return country !== "n/a" && !blocked.some(term => country.includes(term));
      }}
      if (quickState.preset === "fellowships") return item.type === "fellowship";
      if (quickState.preset === "urgent") return typeof item.days_left === "number" && item.days_left >= 0 && item.days_left <= 14;
      return true;
    }}

    function renderSummary(filtered) {{
      const jobs = filtered.filter(item => item.type === "job").length;
      const fellowships = filtered.filter(item => item.type === "fellowship").length;
      const urgent = filtered.filter(item => typeof item.days_left === "number" && item.days_left >= 0 && item.days_left <= 14).length;
      const high = filtered.filter(item => Number(item.match_score || 0) >= 0.12).length;
      const newCount = filtered.filter(item => item.is_new).length;
      const interested = filtered.filter(item => getStatus(item.url) === "interested").length;
      const applied = filtered.filter(item => getStatus(item.url) === "applied").length;
      summaryStripEl.innerHTML = `
        <div class="summary-box"><strong>${{filtered.length}}</strong><span>Visible opportunities</span><small>Current filtered view</small></div>
        <div class="summary-box"><strong>${{jobs}}</strong><span>Jobs</span><small>Current filtered view</small></div>
        <div class="summary-box"><strong>${{fellowships}}</strong><span>Fellowships</span><small>Current filtered view</small></div>
        <div class="summary-box"><strong>${{newCount}}</strong><span>New in current view</span><small>Controlled from sidebar</small></div>
        <div class="summary-box"><strong>${{urgent}}</strong><span>Deadline within 14 days</span><small>Controlled from sidebar</small></div>
        <div class="summary-box"><strong>${{high}}</strong><span>High-match items</span><small>Controlled from sidebar</small></div>
        <div class="summary-box"><strong>${{interested}}</strong><span>Interested in current view</span><small>Status summary</small></div>
        <div class="summary-box"><strong>${{applied}}</strong><span>Applied in current view</span><small>Status summary</small></div>
      `;
    }}

    function renderPriority(filtered) {{
      const priority = filtered
        .slice()
        .sort((a, b) => {{
          const aUrgent = typeof a.days_left === "number" && a.days_left >= 0 ? a.days_left : 9999;
          const bUrgent = typeof b.days_left === "number" && b.days_left >= 0 ? b.days_left : 9999;
          const aScore = Number(a.match_score || 0);
          const bScore = Number(b.match_score || 0);
          return (bScore * 100 - aScore * 100) + (aUrgent - bUrgent) * -0.05;
        }})
        .slice(0, 5);

      priorityCaptionEl.textContent = priority.length
        ? "Best next opportunities to review first."
        : "No opportunities match the current filters.";
      priorityGridEl.innerHTML = priority.length
        ? priority.map(priorityCard).join("")
        : '<div class="empty">No priority items for the current filters.</div>';
    }}

    function renderFocusPanels() {{
      const interested = data
        .filter(item => getStatus(item.url) === "interested")
        .sort((a, b) => deadlineRank(a) - deadlineRank(b) || Number(b.match_score || 0) - Number(a.match_score || 0))
        .slice(0, 8);
      const applied = data
        .filter(item => getStatus(item.url) === "applied")
        .sort((a, b) => deadlineRank(a) - deadlineRank(b) || Number(b.match_score || 0) - Number(a.match_score || 0))
        .slice(0, 8);

      interestedListEl.innerHTML = interested.length
        ? interested.map(focusItem).join("")
        : '<div class="empty">No items marked Interested yet.</div>';
      appliedListEl.innerHTML = applied.length
        ? applied.map(focusItem).join("")
        : '<div class="empty">No items marked Applied yet.</div>';
    }}

    function bindResultsEvents(root = resultsEl) {{
      root.querySelectorAll(".status-btn").forEach(button => {{
        button.addEventListener("click", () => void setStatus(button.dataset.url, button.dataset.status));
      }});
      root.querySelectorAll("[data-keyword-filter]").forEach(chip => {{
        chip.addEventListener("click", () => {{
          searchEl.value = chip.dataset.keywordFilter || "";
          syncKeywordClearButton();
          render();
          showToast(`Filtered by keyword: ${{chip.dataset.keywordFilter || ""}}`);
        }});
      }});
      root.querySelectorAll("[data-save-field]").forEach(button => {{
        button.addEventListener("click", () => {{
          const field = button.dataset.saveField || "";
          const wrapper = button.closest("[data-edit-field]");
          const input = wrapper ? wrapper.querySelector("[data-edit-input]") : null;
          const value = input ? input.value : "";
          if (field === "note") {{
            void saveOpportunityNote(button.dataset.url, value);
          }} else {{
            void saveOpportunityOverride(button.dataset.url, field, value);
          }}
        }});
      }});
      root.querySelectorAll("[data-reset-field]").forEach(button => {{
        button.addEventListener("click", () => {{
          void resetOpportunityOverride(button.dataset.url, button.dataset.resetField || "");
        }});
      }});
    }}

    function render() {{
      const term = searchEl.value.trim().toLowerCase();
      const selectedType = typeFilterEl.value;
      const selectedNew = newFilterEl.value;
      const deadlineLimit = deadlineFilterEl.value;
      const sortBy = sortByEl.value;
      const source = sourceFilterEl.value;
      const country = countryFilterEl.value;
      const institution = institutionFilterEl.value;

        let filtered = data
          .filter(item => applyPreset(item))
          .filter(item => selectedType === "all" ? true : item.type === selectedType)
          .filter(item => selectedNew === "new" ? !!item.is_new : true)
          .filter(item => matchesDeadline(item, deadlineLimit))
          .filter(item => matchesSource(item, source))
        .filter(item => matchesCountry(item, country))
        .filter(item => matchesInstitution(item, institution))
        .filter(item => matchesSearch(item, term))
        .filter(item => quickState.newOnly ? !!item.is_new : true)
        .filter(item => quickState.urgentOnly ? (typeof item.days_left === "number" && item.days_left >= 0 && item.days_left <= 7) : true)
        .filter(item => quickState.highMatchOnly ? Number(item.match_score || 0) >= 0.12 : true)
        .filter(item => quickState.statusView === "all" ? true : quickState.statusView === "unprocessed" ? !getStatus(item.url) : getStatus(item.url) === quickState.statusView)
          .sort((a, b) => compare(a, b, sortBy));

        if (!filtered.length && quickState.statusView === "unprocessed") {{
          const unprocessedExists = data.some(item => !getStatus(item.url));
          const interestedExists = data.some(item => getStatus(item.url) === "interested");
          if (!unprocessedExists && interestedExists) {{
            setStatusView("interested");
            syncQuickToggleButtons();
            filtered = data
              .filter(item => applyPreset(item))
              .filter(item => selectedType === "all" ? true : item.type === selectedType)
              .filter(item => selectedNew === "new" ? !!item.is_new : true)
              .filter(item => matchesDeadline(item, deadlineLimit))
              .filter(item => matchesSource(item, source))
              .filter(item => matchesCountry(item, country))
              .filter(item => matchesInstitution(item, institution))
              .filter(item => matchesSearch(item, term))
              .filter(item => quickState.newOnly ? !!item.is_new : true)
              .filter(item => quickState.urgentOnly ? (typeof item.days_left === "number" && item.days_left >= 0 && item.days_left <= 7) : true)
              .filter(item => quickState.highMatchOnly ? Number(item.match_score || 0) >= 0.12 : true)
              .filter(item => getStatus(item.url) === "interested")
              .sort((a, b) => compare(a, b, sortBy));
            showToast("No unprocessed items left. Switched to Interested view.");
          }}
        }}

      renderSummary(filtered);
      renderPriority(filtered);
      renderFocusPanels();
      renderHeroStatusCounts();

      if (!filtered.length) {{
        resultsEl.innerHTML = `<div class="empty">${{saveError || "No opportunities match the current filters."}}</div>`;
        syncKeywordClearButton();
        return;
      }}

      resultsEl.innerHTML = (saveError ? `<div class="empty">${{saveError}}</div>` : "") + filtered.map(card).join("");
      bindResultsEvents(resultsEl);
      syncKeywordClearButton();
    }}

    [searchEl, typeFilterEl, newFilterEl, deadlineFilterEl, sortByEl, sourceFilterEl, countryFilterEl, institutionFilterEl].forEach(el => {{
      el.addEventListener("input", render);
      el.addEventListener("change", render);
    }});

    clearKeywordFilterEl.addEventListener("click", () => {{
      searchEl.value = "";
      syncKeywordClearButton();
      render();
      showToast("Keyword filter cleared");
    }});

    [
      [toggleNewEl, "newOnly"],
      [toggleUrgentEl, "urgentOnly"],
      [toggleHighMatchEl, "highMatchOnly"],
    ].forEach(([button, key]) => {{
      button.addEventListener("click", () => {{
        quickState[key] = !quickState[key];
        syncQuickToggleButtons();
        render();
      }});
    }});

    toggleAllStatusesEl.addEventListener("click", () => {{
      setStatusView("all");
      syncQuickToggleButtons();
      render();
    }});

    toggleUnprocessedEl.addEventListener("click", () => {{
      setStatusView("unprocessed");
      syncQuickToggleButtons();
      render();
    }});

    toggleIgnoredEl.addEventListener("click", () => {{
      setStatusView(quickState.statusView === "ignored" ? "unprocessed" : "ignored");
      syncQuickToggleButtons();
      render();
    }});

    toggleInterestedEl.addEventListener("click", () => {{
      setStatusView(quickState.statusView === "interested" ? "unprocessed" : "interested");
      syncQuickToggleButtons();
      render();
    }});

    toggleAppliedEl.addEventListener("click", () => {{
      setStatusView(quickState.statusView === "applied" ? "unprocessed" : "applied");
      syncQuickToggleButtons();
      render();
    }});

    syncQuickToggleButtons();
    presetButtons.forEach(button => {{
      button.addEventListener("click", () => {{
        quickState.preset = button.dataset.preset;
        presetButtons.forEach(item => item.classList.toggle("active", item === button));
        render();
      }});
    }});

    saveConfigButtonEl.addEventListener("click", () => void saveConfig(false));
    saveRefreshButtonEl.addEventListener("click", () => void saveConfig(true));
    restoreStatusesButtonEl.addEventListener("click", () => void restoreStatuses());
    undoStatusButtonEl.addEventListener("click", () => void undoLastStatus());

    async function hydrateData() {{
      if (!window.location.protocol.startsWith("http")) {{
        serverIndicatorEl.classList.remove("connected");
        serverIndicatorTextEl.textContent = "Static file mode";
        render();
        return;
      }}
      try {{
        const response = await fetch("/api/opportunities");
        if (!response.ok) throw new Error("fetch failed");
        const payload = await response.json();
        if (payload.ok && Array.isArray(payload.items)) {{
          data = payload.items.map(item => {{
            const numericScore = Number(item.match_score || 0);
            const numericDays = item.days_left === "" ? null : Number(item.days_left);
            return {{
              ...item,
              match_score: Number.isNaN(numericScore) ? 0 : numericScore,
              days_left: Number.isNaN(numericDays) ? null : numericDays,
              is_new: Boolean(item.is_new),
            }};
          }});
          populateSelect(sourceFilterEl, uniqueValues("source_site"), "All source sites");
          populateSelect(countryFilterEl, uniqueValues("country"), "All countries");
          populateSelect(institutionFilterEl, uniqueValues("institution"), "All institutions");
          serverIndicatorEl.classList.add("connected");
          serverIndicatorTextEl.textContent = "Connected to local server";
        }}
      }} catch (error) {{
        serverIndicatorEl.classList.remove("connected");
        serverIndicatorTextEl.textContent = "Server connection failed";
      }}
      bindResultsEvents(resultsEl);
      syncKeywordClearButton();
    }}

    async function pollUpdateStatus() {{
      if (!window.location.protocol.startsWith("http")) {{
        return;
      }}
      try {{
        const response = await fetch("/api/update-status");
        if (!response.ok) return;
        const payload = await response.json();
        if (!payload.ok) return;
        if (payload.running) {{
          showUpdateBanner("Refreshing opportunities in the background...");
        }} else if (payload.failed) {{
          showUpdateBanner("Background refresh failed. Check the server window.", true);
        }} else if (payload.completed) {{
          hideUpdateBanner();
          if (updatePollTimer) {{
            clearInterval(updatePollTimer);
            updatePollTimer = null;
          }}
          await hydrateData();
          showToast("Latest opportunities loaded");
        }} else {{
          hideUpdateBanner();
        }}
      }} catch (error) {{
      }}
    }}

    async function loadSessionWarning() {{
      if (!window.location.protocol.startsWith("http")) {{
        return;
      }}
      try {{
        const response = await fetch("/api/session-status");
        if (!response.ok) return;
        const payload = await response.json();
        if (!payload.ok) return;
        showSessionWarning(payload.warning ? (payload.message || "Another machine appears active.") : "");
      }} catch (error) {{
      }}
    }}

    async function loadSystemState() {{
      if (!systemStateNoteEl) {{
        return;
      }}
      if (!window.location.protocol.startsWith("http")) {{
        systemStateNoteEl.textContent = "Static mode: database status is only available through the local server.";
        renderSourceHealth([]);
        return;
      }}
      try {{
        const response = await fetch("/api/system-state");
        if (!response.ok) throw new Error("fetch failed");
        const payload = await response.json();
        if (!payload.ok) throw new Error("state failed");
        const latestRun = payload.latest_pipeline_run || null;
        const statusHistory = payload.status_history || {{ count: 0 }};
        const latestFailedSource = payload.latest_failed_source || null;
        renderSourceHealth(payload.source_health || []);
        if (!payload.database_available) {{
          systemStateNoteEl.textContent = "Runtime database unavailable. Dashboard data cannot be trusted until the next successful refresh.";
          return;
        }}
        const completedAt = latestRun && latestRun.completed_at ? latestRun.completed_at : "unknown";
        const saved = latestRun && latestRun.opportunities_saved != null ? latestRun.opportunities_saved : "unknown";
        const failureText = latestFailedSource ? ` Last source error: ${{latestFailedSource.source_key}} (${{latestFailedSource.status}}).` : "";
        systemStateNoteEl.textContent = `Runtime database active. Last refresh: ${{completedAt}}. Current opportunities: ${{payload.current_opportunities_count || saved}}. Saved statuses: ${{statusHistory.saved_count || 0}}. Archived opportunities: ${{statusHistory.archive_count || 0}}. Orphan statuses: ${{statusHistory.orphan_count || 0}}.${{failureText}}`;
      }} catch (error) {{
        systemStateNoteEl.textContent = "Could not load runtime database status.";
        renderSourceHealth([]);
      }}
    }}

    bindResultsEvents(resultsEl);
    syncKeywordClearButton();
    void hydrateData();
    void loadConfigEditor();
    void loadSessionWarning();
    void loadSystemState();
    if (window.location.protocol.startsWith("http")) {{
      void pollUpdateStatus();
      updatePollTimer = setInterval(() => void pollUpdateStatus(), 4000);
      setInterval(() => void loadSessionWarning(), 30000);
      setInterval(() => void loadSystemState(), 30000);
    }}
  </script>
  </body>
  </html>"""


def _render_initial_card(item: dict[str, Any]) -> str:
    tags: list[str] = [f'<span class="tag">{escape(str(item.get("type", "") or ""))}</span>']
    score = item.get("match_score", "")
    if score not in {"", None}:
        tags.append(f'<span class="tag">score {escape(str(score))}</span>')
    source = str(item.get("source_site", "") or "").strip()
    if source:
        tags.append(f'<span class="tag">{escape(source)}</span>')
    status = str(item.get("status", "") or "").strip()
    if status:
        tags.append(f'<span class="tag">{escape(status)}</span>')
    days_left = item.get("days_left")
    if isinstance(days_left, int) and days_left >= 0:
        tags.append(f'<span class="tag {"danger" if days_left <= 7 else "warn" if days_left <= 30 else ""}">{days_left} days left</span>')
    matched_keywords = [
        keyword.strip()
        for keyword in str(item.get("matched_keywords", "") or "").split(",")
        if keyword.strip()
    ]
    url = escape(str(item.get("url", "") or ""))
    status = str(item.get("status", "") or "").strip()
    type_value = escape(str(item.get("type", "") or ""))
    source_value = escape(source or "")
    country_value = escape(str(item.get("country", "") or ""))
    institution_value = escape(str(item.get("institution", "") or ""))
    title_value = escape(str(item.get("title", "Untitled") or "Untitled"))
    is_new = "true" if item.get("is_new") else "false"
    days_value = str(days_left if isinstance(days_left, int) else "")
    score_value = escape(str(score if score not in {"", None} else ""))

    return f"""
        <article class="card" data-url="{url}" data-type="{type_value}" data-source="{source_value}" data-country="{country_value}" data-institution="{institution_value}" data-status-current="{escape(status)}" data-is-new="{is_new}" data-days-left="{escape(days_value)}" data-match-score="{score_value}" data-title="{title_value}">
          <div class="card-header">
            <div>
              <h2><a href="{escape(str(item.get("url", "") or ""))}" target="_blank" rel="noreferrer">{title_value}</a></h2>
              <div class="meta">{''.join(tags)}</div>
            </div>
            <div class="actions">
              <a class="button" href="{url}" target="_blank" rel="noreferrer">Open Original Listing</a>
            </div>
          </div>
          <div class="grid">
            <div><strong>Institution</strong>{escape(str(item.get("institution", "") or "N/A"))}</div>
            <div><strong>Department</strong>{escape(str(item.get("department", "") or "N/A"))}</div>
            <div><strong>Location</strong>{escape(str(item.get("location", "") or "N/A"))}</div>
            <div><strong>Country</strong>{escape(str(item.get("country", "") or "N/A"))}</div>
            <div><strong>Salary</strong>{escape(str(item.get("salary", "") or "N/A"))}</div>
            <div><strong>Posted</strong>{escape(str(item.get("posted_date", "") or "N/A"))}</div>
            <div><strong>Deadline</strong>{escape(str(item.get("application_deadline") or item.get("deadline_status") or "N/A"))}</div>
            <div><strong>Source</strong>{escape(source or "N/A")}</div>
          </div>
          <div class="status-row">
            <button class="status-btn {'active' if status == 'interested' else ''}" data-status="interested" data-url="{url}">Interested</button>
            <button class="status-btn {'active' if status == 'applied' else ''}" data-status="applied" data-url="{url}">Applied</button>
            <button class="status-btn {'active' if status == 'ignored' else ''}" data-status="ignored" data-url="{url}">Ignore</button>
            <button class="status-btn {'active' if not status else ''}" data-status="none" data-url="{url}">Clear</button>
          </div>
          {_render_initial_keywords(matched_keywords)}
          <p class="section-label">Opportunity Summary</p>
          <p class="summary">{escape(str(item.get("summary", "") or ""))}</p>
        </article>
    """


def _render_initial_focus_item(item: dict[str, Any]) -> str:
    return f"""
      <article class="focus-item">
        <a href="{escape(str(item.get("url", "") or ""))}" target="_blank" rel="noreferrer">{escape(str(item.get("title", "Untitled") or "Untitled"))}</a>
        <p>{escape(str(item.get("institution", "") or "N/A"))} | {escape(str(item.get("application_deadline") or item.get("deadline_status") or "N/A"))} | score {escape(str(item.get("match_score", "") or ""))}</p>
      </article>
    """


def _render_initial_keywords(matched_keywords: list[str]) -> str:
    if not matched_keywords:
        return ""
    tags = "".join(
        f'<span class="keyword-chip actionable" data-keyword-filter="{escape(keyword)}">{escape(keyword)}</span>'
        for keyword in matched_keywords
    )
    return f"""
      <details class="keyword-details">
        <summary>Matched keywords ({len(matched_keywords)})</summary>
        <div class="keyword-tags">{tags}</div>
      </details>
    """
