"""Causal headline rules for PAPER research; no network calls or price confirmation.

This is an explainable rules engine, not an LLM or a promise of market direction.
Uncertain or contradictory text is recorded without inventing a trade direction.
"""
import html
import re


def _rx(pattern):
    return re.compile(pattern, re.I)


AMBIGUOUS_SYMBOLS = frozenset((
    "NOT", "PEOPLE", "MOVE", "ETC", "TRUMP", "MELANIA", "GAS", "WAR", "ON",
    "OFF", "ONE", "NEW", "NOW", "GO", "US", "USA", "FUN", "OPEN", "CLOSE",
    "TIME", "HIGH", "LOW", "PARTI", "PUMP", "SIGN", "IP", "W", "A", "AI",
    "ACE", "APR", "MAY", "JUNE", "JUL", "FOR", "FORM", "DO", "IN", "TO",
    "ACT", "CAT", "DOG", "RED", "BIG", "SAFE", "BAN", "BAND", "LISTA",
    "NIL", "FARTCOIN",  # require the coin spelling/explicit cashtag for memes
))
ALIASES = {
    "BCH": r"\bbitcoin cash\b",
    "ETC": r"\bethereum classic\b",
    "BTC": r"\bbitcoin\b(?!\s+cash\b)",
    "ETH": r"\b(?:ethereum(?!\s+classic\b)|ether)\b",
    "SOL": r"\bsolana\b",
    "DOGE": r"\bdogecoin\b",
    "BNB": r"\bbinance coin\b",
    "LINK": r"\bchainlink\b",
    "AVAX": r"\bavalanche\s+(?:network|blockchain|token)\b",
    "TAO": r"\bbittensor\b",
    "NOT": r"\bnotcoin\b",
    "PEOPLE": r"\bconstitutiondao\b",
    "MOVE": r"\bmovement\s+(?:network|token|blockchain)\b",
    "SUI": r"\bsui\s+(?:network|token|blockchain)\b",
    "HYPE": r"\bhyperliquid\s+(?:token|coin)\b",
    "FARTCOIN": r"\bfartcoin\b",
}
_ALIASES = tuple((symbol, _rx(pattern)) for symbol, pattern in ALIASES.items())
_CASHTAG = _rx(r"(?<![A-Za-z0-9])\$([A-Za-z0-9]{1,15})\b")
_PAIR = _rx(r"(?<![A-Za-z0-9])([A-Za-z0-9]{1,15})(?:/?USD[TC])\b")
_TOKEN_NAME = _rx(r"\b([A-Za-z0-9]{1,15})\s+(?:token|coin|memecoin)\b")
_BARE_TICKER = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{2,14})(?![A-Za-z0-9])")
_MACRO = _rx(
    r"\b(?:FOMC|CPI|PCE|interest rates?|inflation|rate cuts?|rate hikes?|"
    r"crypto(?:currency)? market|quantitative easing|hawkish pivot|dovish pivot|"
    r"tariffs?|sanctions?|airstrikes?|missiles?|major operations against|"
    r"military|invasion|ceasefire|truce|peace (?:deal|talks|agreement)|"
    r"blockade|Hormuz|Suez|OPEC|recession|government shutdown|sovereign default)\b|"
    r"\b(?:Fed|Federal Reserve|ECB|central bank)\b.{0,35}\b(?:cuts?|raises?|hikes?|lowers?)\s+(?:interest\s+)?rates?\b"
)
_PROMO = _rx(
    r"\b(?:giveaway|sweepstakes|contest|competition|winners?|congratulations|congrats|webinar|meetup|"
    r"podcast|merchandise|merch|awards?|prizes?)\b|\bwin\s+(?:tickets?|a prize)\b"
)
_UNCERTAIN = _rx(
    r"\b(?:could|might|rumou?rs?|unconfirmed|speculat\w*|predict\w*|proposed|proposal|"
    r"projections?|hypothetical|potentially|allegedly)\b|"
    r"\b(?:may|would)\s+(?:be|cut|hike|approve|reject|launch|list|delist|attack|rise|fall)\b|"
    r"\b(?:expected|expects?|forecast|plans?|proposes?)\s+to\b|"
    r"\b(?:leans? toward|weighs?|considering|considers?|no final decision|not finalized|"
    r"not confirmed|cannot confirm|no confirmation|false reports?|fake news|debunked|disproved)\b|"
    r"\bif\b|\b(?:approval|decision)\s+(?:pending|awaited)\b|"
    r"\b(?:not yet|has yet to)\s+(?:be\s+)?(?:approved|approve|confirmed)\b|"
    r"\b(?:seeks?|seeking|applies?|application|files?|filing)\b.{0,35}\b(?:approval|ETF)\b|"
    r"\b(?:odds|probability|bets|expectations?)\b.{0,30}\b(?:rate|cut|hike|approval)\b|"
    r"\b(?:rate cuts?|rate hikes?|ETF approval)\b.{0,25}\b(?:odds|probability|bets|expectations?)\b"
)
_HISTORICAL = _rx(
    r"\b(?:yesterday|last (?:week|month|year)|throwback|recap|retrospective|anniversary)\b|"
    r"\b\d+\s+(?:days?|weeks?|months?|years?)\s+ago\b"
)
_PRICE_UP = _rx(r"\b(?:pump(?:ing|s)?|surges?|soars?|jumps?|rall(?:y|ies)|gains?|rises?|rebounds?|bullish|breakout)\b")
_PRICE_DOWN = _rx(r"\b(?:dump(?:ing|s)?|sell-?offs?|falls?|drops?|slips?|plunges?|tumbles?|declines?|crash(?:es)?|bearish)\b")
_NEGATION = _rx(r"\b(?:not|never|no|without|denies?|denied|refutes?|refuted)\b(?:\W+\w+){0,5}\W*$")

# Specific resolved/negated events suppress their generic opposite below.
_DENIED_HACK = _rx(
    r"\b(?:denies?|denied|refutes?|refuted)\b.{0,45}\b(?:hack|exploit|breach)\b|"
    r"\b(?:no evidence of|not|was not|wasn't)\s+(?:a\s+)?(?:hack(?:ed)?|exploit(?:ed)?|breach)\b|"
    r"\b(?:hack|exploit|breach)\b.{0,35}\b(?:denied|disproved|prevented|false)\b"
)
_RESOLVED_LAWSUIT = _rx(
    r"\b(?:lawsuit|charges?|case)\b.{0,35}\b(?:dismissed|dropped|withdrawn)\b|"
    r"\b(?:drops?|dropped|withdraws?|dismisses?)\b.{0,25}\b(?:lawsuit|charges?|case)\b"
)
_FAILED_CEASEFIRE = _rx(
    r"\b(?:ceasefire|truce|peace (?:deal|talks|agreement))\b.{0,30}\b(?:ends?|broken|violated|collapses?|fails?)\b|"
    r"\b(?:breaks?|violates?|ends?|terminates?)\b.{0,25}\b(?:ceasefire|truce)\b"
)
_ETF_REJECTION = _rx(
    r"\b(?:rejects?|rejected|denies|denied|blocks?|blocked)\b.{0,55}\bETF\b|"
    r"\bETF\b.{0,55}\b(?:rejected|denied|not approved|approval rejected|fails?|failed)\b"
)

_RULES = tuple((name, side, _rx(pattern)) for name, side, pattern in (
    ("ETF_APPROVAL", 1, r"\bETF\b.{0,45}\b(?:approved|approval granted)\b|\bapprov(?:es|ed)\b.{0,45}\b(?:ETF|spot bitcoin|spot ethereum)\b|\bapproval of spot\b"),
    ("DELISTING", -1, r"\bdelist(?:s|ed|ing)?\b"),
    ("LISTING", 1, r"\b(?:will list|lists|listed on|listing(?: of)?)\b"),
    ("BUYBACK", 1, r"\b(?:buybacks?|buy back|repurchase(?:s|d)?)\b"),
    ("ADOPTION", 1, r"\b(?:adoption|adopts?|integrates?|integration|partnership|partners with)\b"),
    ("HACK", -1, r"\b(?:hack(?:s|ed)?|exploit(?:s|ed)?|breach|stolen|drained)\b"),
    ("ENFORCEMENT", -1, r"\b(?:lawsuit|charges|charged|enforcement action)\b|\bbans?\b.{0,25}\b(?:crypto|bitcoin|trading|tokens?)\b"),
    ("FUND_OUTFLOW", -1, r"\b(?:net outflows?|outflows?)\b"),
    ("FUND_INFLOW", 1, r"\b(?:net inflows?|inflows?)\b"),
    ("MONETARY_EASING", 1, r"\b(?:rate cuts?|cuts? (?:interest )?rates?|lowers? (?:interest )?rates?|dovish pivot|quantitative easing)\b"),
    ("MONETARY_TIGHTENING", -1, r"\b(?:rate hikes?|hikes? (?:interest )?rates?|raises? (?:interest )?rates?|hawkish pivot|higher for longer)\b"),
    ("RISK_ON_DEESCALATION", 1, r"\b(?:ceasefire|truce|peace deal|peace agreement|de-escalation)\b|\b(?:sanctions?|tariffs?)\b.{0,25}\b(?:lifted|reduced|removed|relief|exemptions?)\b|\b(?:lifts?|removes?|reduces?)\b.{0,25}\b(?:sanctions?|tariffs?)\b"),
    ("RISK_OFF_GEOPOLITICS", -1, r"\b(?:airstrikes?|missile (?:strikes?|attacks?)|military strikes?|military operations|major operations against|invasion|war escalates|blockade|government shutdown|sovereign default)\b|\b(?:ballistic missiles?)\b.{0,30}\b(?:launched|fired|intercepted)\b|\b(?:sanctions?|tariffs?)\b.{0,25}\b(?:imposed|announced|tightened|hikes?|raised|increased)\b|\b(?:announces?|imposes?|raises?)\b.{0,25}\b(?:sanctions?|tariffs?)\b"),
    ("TOKEN_UNLOCK", -1, r"\b(?:token unlock|tokens? unlocked|unlock(?:s|ing)?\s+\$?\d|vesting release)\b"),
))


def _clean(title):
    text = html.unescape(re.sub(r"<[^>]*>", " ", str(title or "")))
    text = re.sub(r"https?://\S+", " ", text)
    text = text.translate(str.maketrans({"’": "'", "–": "-", "—": "-"}))
    return re.sub(r"\s+", " ", text).strip()


def is_non_market_news(title):
    return bool(_PROMO.search(_clean(title)))


def _targets(text, prices):
    """Return deterministic mentions in textual order, independent of dict order."""
    markets = {str(symbol).upper() for symbol in prices}
    found = {}
    # Scan the text once per spelling form, not once per listed market. The
    # earlier per-market regex loop thrashed Python's regex cache on 225+ assets.
    for pattern in (_CASHTAG, _PAIR, _TOKEN_NAME):
        for match in pattern.finditer(text):
            symbol = match.group(1).upper()
            if symbol in markets:
                found[symbol] = min(found.get(symbol, match.start()), match.start())
    for symbol, pattern in _ALIASES:
        if symbol in markets and (match := pattern.search(text)):
            found[symbol] = min(found.get(symbol, match.start()), match.start())
    # Bare ticker matching is case-sensitive: 'ethics' and 'gas prices' do not
    # become token entities. Ambiguous ordinary words need a cashtag/name.
    for match in _BARE_TICKER.finditer(text):
        symbol = match.group(1)
        if symbol in markets and symbol not in AMBIGUOUS_SYMBOLS:
            found[symbol] = min(found.get(symbol, match.start()), match.start())
    mentions = sorted(found, key=lambda symbol: (found[symbol], symbol))
    if mentions:
        return mentions
    if _MACRO.search(text):
        return [symbol for symbol in ("BTC", "ETH") if symbol in markets][:1]
    return []


def _inflation_surprise(text):
    if not re.search(r"\b(?:CPI|PCE|inflation)\b", text, re.I):
        return None
    directional = re.search(r"\b(above|higher than|below|lower than)\s+(?:the\s+)?(?:expectations?|expected|forecast|consensus)\b", text, re.I)
    if directional:
        return (-1 if directional.group(1).lower() in ("above", "higher than") else 1, directional.group(0))
    # Compare an explicitly labelled expectation, never the previous observation.
    number = r"([0-9]+(?:\.[0-9]+)?)\s*%?"
    patterns = (
        number + r"\s*(?:vs\.?|versus)\s*" + number + r"\s*(?:exp(?:ected)?|forecast|consensus)\b",
        number + r"\s*(?:vs\.?|versus)\s*(?:exp(?:ected)?|forecast|consensus)\s*:?\s*" + number,
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            actual, expected = map(float, match.groups())
            return (1 if actual < expected else -1 if actual > expected else 0, match.group(0))
    return None


def _negated(text, match, allow_not_approved=False):
    prefix = re.split(r"[.!;:]", text[:match.start()])[-1][-65:]
    prefix = re.sub(r"\$NOT\b|\bNOT(?=\s+(?:token|coin|memecoin)\b)", "TOKEN", prefix, flags=re.I)
    inside = match.group(0)
    if allow_not_approved:
        inside = re.sub(r"\bnot approved\b", "REJECTED", inside, flags=re.I)
    return bool(_NEGATION.search(prefix) or re.search(r"\b(?:not|no|never|without)\b", inside, re.I))


def analyze_headline(title, prices):
    """Return entity, direction and auditable evidence from one headline.

    ``uncertainty`` is a list of refusal reasons, not a numerical confidence.
    A neutral result still retains its known symbol for the research journal.
    """
    text = _clean(title)
    mentions = _targets(text, prices)
    result = {"symbol": mentions[0] if mentions else None, "side": 0,
              "event_type": "UNCLASSIFIED", "reason": "no_causal_direction",
              "evidence": [], "uncertainty": [], "entities": mentions,
              "classifier": "causal_rules_v1"}

    def refuse(reason, event_type="UNCLASSIFIED"):
        result.update(side=0, event_type=event_type, reason=reason, uncertainty=[reason])
        return result

    if not text:
        return refuse("empty_headline")
    if is_non_market_news(text):
        return refuse("promotional_or_non_market_event", "NON_MARKET")
    if len(mentions) > 1:
        return refuse("multiple_target_assets", "AMBIGUOUS_TARGET")
    if not mentions:
        return refuse("no_tradable_market")
    if "?" in text or _UNCERTAIN.search(text):
        return refuse("conditional_or_unconfirmed_event", "UNCERTAIN")
    if _HISTORICAL.search(text):
        return refuse("historical_or_recap_event", "HISTORICAL")
    if (re.search(r"\bceasefire\b.{0,20}\b(?:talks?|negotiations?|offers?)\b", text, re.I)
            and not _FAILED_CEASEFIRE.search(text)):
        return refuse("unresolved_ceasefire_negotiations", "UNCERTAIN")

    surprise = _inflation_surprise(text)
    events = []
    if surprise:
        side, evidence = surprise
        events.append(("INFLATION_SURPRISE", side, evidence))

    denied_hack = _DENIED_HACK.search(text)
    resolved_lawsuit = _RESOLVED_LAWSUIT.search(text)
    failed_ceasefire = _FAILED_CEASEFIRE.search(text)
    rejected_etf = _ETF_REJECTION.search(text)
    for match, name, side in ((resolved_lawsuit, "ENFORCEMENT_RESOLVED", 1),
                              (failed_ceasefire, "CEASEFIRE_FAILED", -1),
                              (rejected_etf, "ETF_REJECTION", -1)):
        if match and not _negated(text, match, allow_not_approved=name == "ETF_REJECTION"):
            events.append((name, side, match.group(0)))
    for name, side, pattern in _RULES:
        if ((name == "HACK" and denied_hack) or
            (name == "ENFORCEMENT" and resolved_lawsuit) or
            (name == "RISK_ON_DEESCALATION" and failed_ceasefire) or
            (name == "ETF_APPROVAL" and rejected_etf)):
            continue
        match = pattern.search(text)
        if not match:
            continue
        # Scope simple negation to the immediately preceding words, not an
        # unrelated earlier sentence ('not a hack. SEC approves ETF').
        if _negated(text, match):
            continue
        suffix = re.split(r"[.!;:]", text[match.end():])[0][:35]
        if name in ("LISTING", "ADOPTION", "BUYBACK") and re.match(r"\s+(?:(?:claim|report|rumor)s?\s+)?(?:denied|cancelled|canceled|false|refuted)\b", suffix, re.I):
            continue
        events.append((name, side, match.group(0)))

    result["evidence"] = [{"event_type": name, "side": side, "text": evidence}
                          for name, side, evidence in events]
    directions = {side for _, side, _ in events if side}
    if len(directions) > 1:
        return refuse("conflicting_causal_events", "MIXED_NEWS")
    if events:
        result.update(event_type=events[0][0], side=next(iter(directions), 0),
                      reason="causal_event" if directions else "no_macro_surprise")
        return result
    if denied_hack:
        result["evidence"] = [{"event_type": "HACK_DENIED", "side": 0, "text": denied_hack.group(0)}]
        return refuse("threat_denied_not_confirmed", "HACK_DENIED")
    if re.search(r"\b(?:CPI|PCE|inflation)\b", text, re.I):
        return refuse("missing_macro_consensus_comparison", "MACRO_UNRESOLVED")
    up, down = bool(_PRICE_UP.search(text)), bool(_PRICE_DOWN.search(text))
    if up or down:
        result.update(event_type="PRICE_ACTION", side=1 if up and not down else -1 if down and not up else 0,
                      reason="delegate_to_pump_dump_scanner")
    return result
