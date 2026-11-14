!/usr/bin/env python3
"""Genera docs/meteo.ics con un evento "tutto il giorno" per ogni giorno di previsione.
Dati: Open-Meteo (gratuito, senza chiave). Cambia CITY/LAT/LON per un'altra città."""
import json, os, socket, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone

CITY = os.environ.get("CITY", "Milano")
LAT = float(os.environ.get("LAT", "45.4642"))
LON = float(os.environ.get("LON", "9.1900"))
MODEL = os.environ.get("MODEL", "")  # vuoto = best_match; es. "icon_seamless", "ecmwf_ifs025"
DAYS = int(os.environ.get("DAYS", "14"))
OUT = os.environ.get("OUT", "docs/meteo.ics")

# Codici WMO -> (emoji, descrizione)
WMO = {
    0: ("☀️", "Sereno"), 1: ("🌤️", "Prevalentemente sereno"), 2: ("⛅", "Parzialmente nuvoloso"),
    3: ("☁️", "Coperto"), 45: ("🌫️", "Nebbia"), 48: ("🌫️", "Nebbia con brina"),
    51: ("🌦️", "Pioviggine leggera"), 53: ("🌦️", "Pioviggine"), 55: ("🌦️", "Pioviggine intensa"),
    56: ("🌧️", "Pioviggine gelata"), 57: ("🌧️", "Pioviggine gelata intensa"),
    61: ("🌧️", "Pioggia debole"), 63: ("🌧️", "Pioggia"), 65: ("🌧️", "Pioggia forte"),
    66: ("🌧️", "Pioggia gelata"), 67: ("🌧️", "Pioggia gelata forte"),
    71: ("🌨️", "Neve debole"), 73: ("🌨️", "Neve"), 75: ("❄️", "Neve forte"), 77: ("🌨️", "Granelli di neve"),
    80: ("🌦️", "Rovesci deboli"), 81: ("🌧️", "Rovesci"), 82: ("⛈️", "Rovesci violenti"),
    85: ("🌨️", "Rovesci di neve"), 86: ("❄️", "Rovesci di neve forti"),
    95: ("⛈️", "Temporale"), 96: ("⛈️", "Temporale con grandine"), 99: ("⛈️", "Temporale con forte grandine"),
}
SNOW_CODES = {71, 73, 75, 77, 85, 86}

_getaddrinfo = socket.getaddrinfo

def _solo_ipv4(*args, **kwargs):
    """Usa solo indirizzi IPv4: su alcuni server di GitHub IPv6 causa timeout."""
    return [r for r in _getaddrinfo(*args, **kwargs) if r[0] == socket.AF_INET]

def fetch():
    params = (
        f"latitude={LAT}&longitude={LON}&timezone=Europe%2FRome&forecast_days={DAYS}"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,precipitation_sum,snowfall_sum"
    )
    if MODEL:
        params += f"&models={MODEL}"
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    last = None
    for attempt in range(1, 6):  # fino a 5 tentativi con pausa crescente
        if attempt >= 2:
            socket.getaddrinfo = _solo_ipv4  # dal 2° tentativo forza IPv4
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            last = e
            print(f"Tentativo {attempt}/5 fallito: {e}", file=sys.stderr)
            if attempt < 5:
                time.sleep(10 * attempt)
    raise last

def esc(t):
    return t.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

def fold(line):
    """Spezza le righe a 75 byte come richiede RFC 5545."""
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    parts, cur = [], b""
    limit = 75
    for ch in line:
        cb = ch.encode("utf-8")
        if len(cur) + len(cb) > limit:
            parts.append(cur.decode("utf-8"))
            cur, limit = b"", 74
        cur += cb
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)

def build(data):
    d = data["daily"]
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//meteo-ics//IT", "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH", f"X-WR-CALNAME:{esc('Meteo ' + CITY)}", "X-WR-TIMEZONE:Europe/Rome",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H",
    ]
    for i, day in enumerate(d["time"]):
        code = int(d["weather_code"][i] or 0)
        emoji, desc = WMO.get(code, ("🌡️", "Variabile"))
        tmax, tmin = d["temperature_2m_max"][i], d["temperature_2m_min"][i]
        prob = d["precipitation_probability_max"][i]
        rain, snow = d["precipitation_sum"][i] or 0, d["snowfall_sum"][i] or 0
        kind = "neve" if (code in SNOW_CODES or snow > 0) else "pioggia"
        prob_txt = f"{round(prob)}%" if prob is not None else "n.d."
        summary = f"{emoji} {round(tmax)}°/{round(tmin)}° · {kind} {prob_txt}"
        descr = (f"{desc}\nMassima: {round(tmax)}°C\nMinima: {round(tmin)}°C\n"
                 f"Rischio {kind}: {prob_txt}\nPrecipitazioni previste: {rain:.1f} mm"
                 + (f" (neve: {snow:.1f} cm)" if snow > 0 else "")
                 + f"\nFonte: Open-Meteo · aggiornato {datetime.now().strftime('%d/%m %H:%M')} UTC")
        start = date.fromisoformat(day)
        end = start + timedelta(days=1)
        lines += [
            "BEGIN:VEVENT",
            f"UID:meteo-{CITY.lower()}-{start:%Y%m%d}@meteo-ics",
            f"DTSTAMP:{now}",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{end:%Y%m%d}",
            f"SUMMARY:{esc(summary)}",
            f"DESCRIPTION:{esc(descr)}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"

if __name__ == "__main__":
    try:
        data = fetch()
    except Exception as e:
        # Problema di rete: teniamo il file precedente e non segnaliamo errore,
        # così non arrivano e-mail per un disguido passeggero.
        print(f"::warning::Open-Meteo non raggiungibile, file non aggiornato: {e}")
        sys.exit(0)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write(build(data))
    print(f"Scritto {OUT} ({len(data['daily']['time'])} giorni)")
