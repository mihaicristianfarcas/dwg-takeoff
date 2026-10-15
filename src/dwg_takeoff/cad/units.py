"""Drawing units: what one drawing unit is in metres, and how sure we are.

The DXF header ($INSUNITS) is often missing ("unitless") or wrong - e.g. US civil plans drawn in
feet but saved with inches, or architectural drawings in millimetres saved as unitless. Every
quantity scales with this factor (areas with its square), so the choice is made explicit: the
header value is kept unless the drawing itself clearly contradicts it, the evidence is reported,
and the user can override it.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field

UNIT_TO_METERS = {0: 1.0, 1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 14: 0.1}
UNIT_NAMES = {0: "unitless", 1: "inches", 2: "feet", 4: "millimeters", 5: "centimeters", 6: "meters", 14: "decimeters"}
# units a user can pick (code -> label shown in the UI)
CHOICES = {6: "metri", 4: "milimetri", 5: "centimetri", 14: "decimetri", 2: "picioare (ft)", 1: "țoli (in)"}

_FEET_MARK = re.compile(r"\d\s*'(?!\s*-?\s*\d)|\d\s*(?:ft|feet)\b|R\.?O\.?W\.?", re.I)
_BEARING = re.compile(r"\b[NS]\s*\d{1,2}\s*°\s*\d{1,2}\s*'\s*\d{0,2}\"?\s*[EW]\b", re.I)


@dataclass
class UnitInfo:
    code: int  # effective unit code (0 = unitless treated as metres)
    scale: float  # drawing unit -> metres
    name: str
    source: str  # header | inferred | default | override
    header_code: int
    confidence: str  # high | medium | low
    evidence: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.source == "default":
            return "unitless (assumed meters)"
        if self.source == "inferred":
            return f"{self.name} (inferred; header says {UNIT_NAMES.get(self.header_code, self.header_code)})"
        if self.source == "override":
            return f"{self.name} (set by user)"
        return self.name

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label
        return d


def _percentile(vals: list[float], q: float) -> float:
    vals = sorted(vals)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def _extent(features) -> float:
    """Robust size of the drawn content (drawing units): diagonal of the 2-98 % box of the
    entities' corners (stray entities far from the plan do not count)."""
    xs, ys = [], []
    for f in features:
        if f.kind == "text" or f.geom.is_empty:
            continue
        b = f.geom.bounds
        xs += (b[0], b[2])
        ys += (b[1], b[3])
    if len(xs) < 2:
        return 0.0
    return math.hypot(_percentile(xs, 0.98) - _percentile(xs, 0.02), _percentile(ys, 0.98) - _percentile(ys, 0.02))


def _plausible_extent(m: float) -> float:
    """How plausible a drawn extent (metres) is for a construction drawing (detail to site plan)."""
    if m <= 0:
        return 0.0
    if 1 <= m <= 5000:
        return 1.0
    return max(0.0, 1 - abs(math.log10(m / (1 if m < 1 else 5000))))


def _plausible_text(m: float) -> float:
    if m <= 0:
        return 0.5  # unknown
    if 0.002 <= m <= 6:
        return 1.0
    return max(0.0, 1 - abs(math.log10(m / (0.002 if m < 0.002 else 6))))


# blocks whose real size is known: (name pattern, plausible longest side in metres, label)
KNOWN_OBJECTS = [
    (
        re.compile(
            r"car|auto|vehicle|ma[sș]in|subaru|toyota|bmw|audi|mercedes|volvo|ford|opel|dacia|renault|"
            r"skoda|volkswagen|\bvw\b|sedan|suv|hatchback|авто|машин",
            re.I,
        ),
        (3.4, 6.2),
        "mașini",
    ),
    (re.compile(r"door|\bu[sș][aă]\b|usi|uși|дверь", re.I), (0.6, 2.4), "uși"),
    (re.compile(r"bench|banc[aă]|скамь|скамей|лавк", re.I), (0.8, 3.5), "bănci"),
    (re.compile(r"\bbin\b|_bin|trash|litter|gunoi|урн", re.I), (0.25, 1.5), "coșuri de gunoi"),
    (re.compile(r"tree|arbor|copac|\bpine|brad|stejar|tei\b|дерев|сосн|\bель", re.I), (0.5, 25.0), "arbori"),
    (re.compile(r"bush|shrub|arbust|куст", re.I), (0.3, 8.0), "arbuști"),
]


def known_object_sizes(features) -> dict[str, list[float]]:
    """Longest side (drawing units) of placed blocks whose names say what they are (cars,
    doors), measured from their exploded geometry."""
    names = {}
    for f in features:
        if f.kind == "block" and not f.nested and f.block:
            for rx, _, label in KNOWN_OBJECTS:
                if rx.search(f.block):
                    names[f.handle] = label
                    break
    if not names:
        return {}
    ext: dict[str, list[float]] = {}
    for f in features:
        if f.handle in names and f.nested and f.kind not in ("text", "block") and not f.geom.is_empty:
            b = f.geom.bounds
            e = ext.setdefault(f.handle, list(b))
            e[0], e[1], e[2], e[3] = min(e[0], b[0]), min(e[1], b[1]), max(e[2], b[2]), max(e[3], b[3])
    out: dict[str, list[float]] = {}
    for h, e in ext.items():
        size = max(e[2] - e[0], e[3] - e[1])
        if size > 0:
            out.setdefault(names[h], []).append(size)
    return out


def object_units(sizes: dict[str, list[float]]) -> tuple[list[int], str] | None:
    """Units in which the known objects have their real-world size (most of them agreeing)."""
    fits, desc = [], ""
    for code, m in UNIT_TO_METERS.items():
        if code == 0:
            continue
        ok = total = 0
        parts = []
        for _, (lo, hi), label in KNOWN_OBJECTS:
            vals = sizes.get(label, [])
            if not vals:
                continue
            med = _percentile(vals, 0.5)
            total += len(vals)
            good = sum(1 for v in vals if lo <= v * m <= hi)
            ok += good
            parts.append(f"{len(vals)} {label} (lungime tipică {med:.3g} unități)")
        if total >= 2 and ok >= max(2, 0.6 * total):
            fits.append(code)
            desc = ", ".join(parts)
    return (fits, desc) if fits else None


def dimension_scale(dims) -> tuple[float, int, float] | None:
    """Consistent ratio displayed/drawn of the linear dimensions: (ratio, agreeing, median value)."""
    ratios = [v / m for m, v in dims or [] if m > 0 and v > 0]
    if len(ratios) < 3:
        return None
    med = _percentile(ratios, 0.5)
    agree = sum(1 for r in ratios if abs(r - med) <= 0.03 * med)
    if agree < max(3, 0.6 * len(ratios)):
        return None
    return med, agree, _percentile([v for _, v in dims], 0.5)


def infer_units(
    header_code: int,
    features,
    measurement: int | None = None,
    lunits: int | None = None,
    override: int | dict | None = None,
    dims=None,
) -> UnitInfo:
    """`override`: a unit code chosen by the user, or {"scale": metres per drawing unit} calibrated
    on a known length (drawings made at plot scale fit no standard unit)."""
    if isinstance(override, dict) and override.get("scale"):
        sc = float(override["scale"])
        return UnitInfo(
            -1,
            sc,
            f"1 unitate = {sc:g} m",
            "override",
            header_code,
            "high",
            [f"scară calibrată de utilizator pe o lungime cunoscută: 1 unitate = {sc:g} m"],
        )
    if override in UNIT_TO_METERS and override != 0:
        return UnitInfo(
            override,
            UNIT_TO_METERS[override],
            UNIT_NAMES[override],
            "override",
            header_code,
            "high",
            ["unități alese manual de utilizator"],
        )
    ext = _extent(features)
    heights = [f.text_height for f in features if f.kind == "text" and f.text_height and not f.nested]
    th = _percentile(heights, 0.5) if heights else 0.0
    texts = [f.text for f in features if f.kind == "text" and f.text]
    feet_marks = sum(1 for t in texts if _FEET_MARK.search(t))
    bearings = sum(1 for t in texts if _BEARING.search(t))
    imperial = measurement == 0 or lunits in (3, 4)  # $MEASUREMENT 0 = imperial; LUNITS 3/4 = eng./arch.

    def describe(code):
        sc = UNIT_TO_METERS[code]
        return f"întindere desen ≈ {ext * sc:,.{0 if ext * sc >= 10 else 2}f} m".replace(",", " ") + (
            f", text tipic {th * sc:.3f} m" if th else ""
        )

    def plaus(code):
        sc = UNIT_TO_METERS[code]
        return _plausible_extent(ext * sc) + _plausible_text(th * sc)

    order = [2, 1, 4, 5, 6, 14] if imperial else [6, 4, 5, 14, 2, 1]  # tie-break preference

    def best_alternative(exclude):
        cands = [c for c in order if c != exclude]
        return max(cands, key=lambda c: (round(plaus(c), 2), -order.index(c)))

    evidence = []
    ds = dimension_scale(dims)
    dim_code = None
    if ds:
        ratio, agree, med_val = ds
        decimals = sum(1 for _, v in dims if abs(v - round(v)) > 1e-6) / len(dims)
        if not imperial:
            # values shown with decimals and small -> metres; whole numbers in the hundreds+ -> millimetres
            display_m = (
                1.0 if decimals >= 0.5 and med_val < 1000 else 0.001 if decimals < 0.2 and med_val >= 100 else None
            )
            if display_m:
                real = ratio * display_m
                dim_code = next((c for c, m in UNIT_TO_METERS.items() if c and abs(m - real) <= 0.03 * real), None)
        if dim_code:
            evidence.append(
                f"{agree} cote liniare: valoarea afișată = {ratio:g} × lungimea desenată "
                f"(ex. {med_val:g}) → 1 unitate = {UNIT_NAMES[dim_code]}"
            )
    ou = object_units(known_object_sizes(features))
    obj_code = None
    if ou:
        fits = ou[0]
        # the header wins when it is among the units that fit; otherwise the most plausible fit
        obj_code = (
            header_code
            if header_code in fits
            else max(fits, key=lambda c: (round(plaus(c), 2), -order.index(c) if c in order else -99))
        )
        evidence.append(f"obiecte de mărime cunoscută: {ou[1]} → 1 unitate = {UNIT_NAMES[obj_code]}")
    if feet_marks or bearings:
        evidence.append(
            f"{feet_marks + bearings} texte cu cote în picioare / orientări topografice (ex. 50', N16°44'49\"W)"
        )
    if header_code in UNIT_TO_METERS and header_code != 0:
        info = UnitInfo(
            header_code,
            UNIT_TO_METERS[header_code],
            UNIT_NAMES[header_code],
            "header",
            header_code,
            "high",
            [f"antet DXF $INSUNITS = {UNIT_NAMES[header_code]}; {describe(header_code)}", *evidence],
        )
        if ext <= 0:
            return info
        if dim_code == header_code:
            return info  # dimensions confirm the header
        if obj_code == header_code and dim_code is None:
            return info  # objects of known size confirm the header
        # object sizes are softer evidence than dimensions: they only override a doubtful header
        if dim_code is None and obj_code is not None and plaus(header_code) < 1.5:
            dim_code = obj_code
        if dim_code and plaus(dim_code) >= plaus(header_code):
            return UnitInfo(
                dim_code,
                UNIT_TO_METERS[dim_code],
                UNIT_NAMES[dim_code],
                "inferred",
                header_code,
                "medium",
                [
                    f"antetul spune {UNIT_NAMES[header_code]} ({describe(header_code)}), dar "
                    f"{'cotele' if ds else 'obiectele de mărime cunoscută'} indică "
                    f"{UNIT_NAMES[dim_code]} ({describe(dim_code)})",
                    *evidence,
                ],
            )
        if header_code == 1 and feet_marks + bearings >= 3 and plaus(2) >= 1.5:
            # US civil plans are drawn in feet but often saved as inches
            info = UnitInfo(
                2,
                UNIT_TO_METERS[2],
                UNIT_NAMES[2],
                "inferred",
                header_code,
                "medium",
                [f"antetul spune inches ({describe(1)}), dar textele cotează în picioare ({describe(2)})", *evidence],
            )
            return info
        best = best_alternative(header_code)
        if plaus(header_code) < 1.0 and plaus(best) >= 1.8:
            return UnitInfo(
                best,
                UNIT_TO_METERS[best],
                UNIT_NAMES[best],
                "inferred",
                header_code,
                "medium",
                [
                    f"antetul spune {UNIT_NAMES[header_code]} ({describe(header_code)}), "
                    f"dar desenul corespunde unor {UNIT_NAMES[best]} ({describe(best)})",
                    *evidence,
                ],
            )
        if plaus(header_code) < 1.5:
            info.confidence = "medium"
            info.evidence.append("dimensiunile desenului sunt neobișnuite pentru aceste unități - verificați")
        return info
    # unitless / unknown code: metres unless metres are clearly implausible
    if ext <= 0:
        return UnitInfo(6, 1.0, "meters", "default", header_code, "low", ["desen fără unități; se presupun metri"])
    if dim_code is None and obj_code is not None:
        dim_code = obj_code
    if dim_code:
        return UnitInfo(
            dim_code,
            UNIT_TO_METERS[dim_code],
            UNIT_NAMES[dim_code],
            "inferred",
            header_code,
            "high",
            [
                f"desen fără unități în antet; {'cotele' if ds else 'obiectele de mărime cunoscută'} indică "
                f"{UNIT_NAMES[dim_code]} ({describe(dim_code)})",
                *evidence,
            ],
        )
    if plaus(6) >= 1.5:
        return UnitInfo(
            6,
            1.0,
            "meters",
            "default",
            header_code,
            "medium",
            [f"desen fără unități în antet; se presupun metri ({describe(6)})", *evidence],
        )
    best = best_alternative(None)
    if plaus(best) < plaus(6) + 0.5:
        return UnitInfo(
            6,
            1.0,
            "meters",
            "default",
            header_code,
            "low",
            [f"desen fără unități în antet; se presupun metri ({describe(6)}) - verificați", *evidence],
        )
    return UnitInfo(
        best,
        UNIT_TO_METERS[best],
        UNIT_NAMES[best],
        "inferred",
        header_code,
        "medium",
        [f"desen fără unități în antet; mărimile corespund unor {UNIT_NAMES[best]} ({describe(best)})", *evidence],
    )
