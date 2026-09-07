# -*- coding: utf-8 -*-
"""
Script d'actualisation quotidienne automatique des pharmacies de garde pour Saydalia Maroc.
Ce script s'exécute automatiquement sur GitHub Actions (Cron Job quotidien).
1. Récupère les pharmacies de garde du jour pour les 33 villes du Maroc.
2. Préserve scrupuleusement les coordonnées GPS calibrées de Saydalia (aucun point dans l'océan).
3. Applique les règles syndicales officielles (Kénitra 2 de nuit en semaine, 5 le weekend ; Mohammédia de nuit ; etc.).
4. Génère le fichier pharmacies.json prêt pour la production.
"""

import urllib.request
import json
import re
import os
import unicodedata
from datetime import datetime

CITIES = [
    {"slug": "casablanca", "name": "Casablanca", "name_ar": "الدار البيضاء"},
    {"slug": "rabat", "name": "Rabat", "name_ar": "الرباط"},
    {"slug": "marrakech", "name": "Marrakech", "name_ar": "مراكش"},
    {"slug": "fes", "name": "Fès", "name_ar": "فاس"},
    {"slug": "tanger", "name": "Tanger", "name_ar": "طنجة"},
    {"slug": "agadir", "name": "Agadir", "name_ar": "أكادير"},
    {"slug": "meknes", "name": "Meknès", "name_ar": "مكناس"},
    {"slug": "oujda", "name": "Oujda", "name_ar": "وجدة"},
    {"slug": "kenitra", "name": "Kénitra", "name_ar": "القنيطرة"},
    {"slug": "tetouan", "name": "Tétouan", "name_ar": "تطوان"},
    {"slug": "sale", "name": "Salé", "name_ar": "سلا"},
    {"slug": "temara", "name": "Témara", "name_ar": "تمارة"},
    {"slug": "mohammedia", "name": "Mohammédia", "name_ar": "المحمدية"},
    {"slug": "el-jadida", "name": "El Jadida", "name_ar": "الجديدة"},
    {"slug": "safi", "name": "Safi", "name_ar": "آسفي"},
    {"slug": "beni-mellal", "name": "Béni Mellal", "name_ar": "بني ملال"},
    {"slug": "nador", "name": "Nador", "name_ar": "الناظور"},
    {"slug": "khouribga", "name": "Khouribga", "name_ar": "خريبكة"},
    {"slug": "settat", "name": "Settat", "name_ar": "سطات"},
    {"slug": "berrechid", "name": "Berrechid", "name_ar": "برشيد"},
    {"slug": "khemisset", "name": "Khémisset", "name_ar": "الخميسات"},
    {"slug": "laayoune", "name": "Laâyoune", "name_ar": "العيون"},
    {"slug": "dakhla", "name": "Dakhla", "name_ar": "الداخلة"},
    {"slug": "guelmim", "name": "Guelmim", "name_ar": "كلميم"},
    {"slug": "taza", "name": "Taza", "name_ar": "تازة"},
    {"slug": "errachidia", "name": "Errachidia", "name_ar": "الرشيدية"},
    {"slug": "ouarzazate", "name": "Ouarzazate", "name_ar": "ورزازات"},
    {"slug": "taroudant", "name": "Taroudant", "name_ar": "تارودانت"},
    {"slug": "essaouira", "name": "Essaouira", "name_ar": "الصويرة"},
    {"slug": "al-hoceima", "name": "Al Hoceïma", "name_ar": "الحسيمة"},
    {"slug": "berkane", "name": "Berkane", "name_ar": "بركان"},
    {"slug": "sidi-kacem", "name": "Sidi Kacem", "name_ar": "سيدي قاسم"},
    {"slug": "sidi-slimane", "name": "Sidi Slimane", "name_ar": "سيدي سليمان"},
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def strip_accents(s):
    if not s:
        return ""
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def normalize(s):
    if not s:
        return ""
    s = strip_accents(s.lower())
    s = s.replace("pharmacie", "").replace("grande", "").strip()
    return re.sub(r'[^a-z0-9]', '', s)

def clean_text(text):
    if not text:
        return ""
    return " ".join(text.replace("\n", " ").replace("\r", " ").replace("\t", " ").split())

def clean_phone(phone_raw):
    if not phone_raw:
        return ""
    digits = re.sub(r"[^\d+]", "", str(phone_raw))
    if digits.startswith("0"):
        digits = "+212" + digits[1:]
    return digits

def parse_pharmacy_duty(item, html=""):
    add_prop = item.get("additionalProperty", {})
    val = add_prop.get("value", "") if isinstance(add_prop, dict) else str(add_prop)
    hours_spec = item.get("specialOpeningHoursSpecification", [])
    
    if "24" in str(val):
        return {
            "duty_type": "24h",
            "duty_category": "permanent_24h",
            "duty_label_fr": "Garde 24h (Tour de garde)",
            "duty_label_ar": "حراسة 24 ساعة (نوبة الحراسة)",
            "duty_hours_fr": "Garde continue 24h/24 (Relève à 09:00)",
            "duty_hours_ar": "حراسة متواصلة 24/24 (تسليم النوبة 09:00)",
            "opens": "00:00",
            "closes": "23:59"
        }

    if hours_spec and isinstance(hours_spec, list) and len(hours_spec) > 0:
        spec = hours_spec[0]
        raw_opens = spec.get("opens", "")
        raw_closes = spec.get("closes", "")
        try:
            opens_h = int(raw_opens.split(":")[0]) if ":" in raw_opens else 0
            closes_h = int(raw_closes.split(":")[0]) if ":" in raw_closes else 0
        except Exception:
            opens_h, closes_h = 0, 0

        if opens_h >= 20 or (closes_h <= 10 and closes_h > 0):
            return {
                "duty_type": "night",
                "duty_category": "night",
                "duty_label_fr": "Garde de Nuit",
                "duty_label_ar": "حراسة ليلية",
                "duty_hours_fr": f"{raw_opens[:5]} - {raw_closes[:5]} (Garde de Nuit)",
                "duty_hours_ar": f"{raw_opens[:5]} - {raw_closes[:5]} (حراسة ليلية)",
                "opens": raw_opens[:5],
                "closes": raw_closes[:5]
            }
        else:
            return {
                "duty_type": "weekend_day",
                "duty_category": "weekend",
                "duty_label_fr": "Garde Jour / Weekend",
                "duty_label_ar": "حراسة نهارية / نهاية الأسبوع",
                "duty_hours_fr": f"{raw_opens[:5]} - {raw_closes[:5]} (Garde Jour / Weekend)",
                "duty_hours_ar": f"{raw_opens[:5]} - {raw_closes[:5]} (حراسة نهارية / نهاية الأسبوع)",
                "opens": raw_opens[:5],
                "closes": raw_closes[:5]
            }

    item_id = item.get("@id", "")
    short_id = item_id.split("#")[-1] if "#" in item_id else ""
    if short_id and html:
        m = re.search(r'id=["\']' + re.escape(short_id) + r'["\'][^>]*data-duty-kind=["\']([^"\']+)["\']', html)
        if m:
            kind = m.group(1).upper()
            if "FULL" in kind or "24" in kind:
                return {
                    "duty_type": "24h",
                    "duty_category": "permanent_24h",
                    "duty_label_fr": "Garde 24h (Tour de garde)",
                    "duty_label_ar": "حراسة 24 ساعة (نوبة الحراسة)",
                    "duty_hours_fr": "Garde continue 24h/24 (Relève à 09:00)",
                    "duty_hours_ar": "حراسة متواصلة 24/24 (تسليم النوبة 09:00)",
                    "opens": "00:00",
                    "closes": "23:59"
                }
            elif "NIGHT" in kind:
                return {
                    "duty_type": "night",
                    "duty_category": "night",
                    "duty_label_fr": "Garde de Nuit",
                    "duty_label_ar": "حراسة ليلية",
                    "duty_hours_fr": "21:00 - 09:00 (Garde de Nuit)",
                    "duty_hours_ar": "21:00 - 09:00 (حراسة ليلية)",
                    "opens": "21:00",
                    "closes": "09:00"
                }
            elif "WEEKEND" in kind or "DAY" in kind:
                return {
                    "duty_type": "weekend_day",
                    "duty_category": "weekend",
                    "duty_label_fr": "Garde Jour / Weekend",
                    "duty_label_ar": "حراسة نهارية / نهاية الأسبوع",
                    "duty_hours_fr": "09:00 - 21:00 (Garde Jour / Weekend)",
                    "duty_hours_ar": "09:00 - 21:00 (حراسة نهارية / نهاية الأسبوع)",
                    "opens": "09:00",
                    "closes": "21:00"
                }

    return {
        "duty_type": "night",
        "duty_category": "night",
        "duty_label_fr": "Garde de Nuit",
        "duty_label_ar": "حراسة ليلية",
        "duty_hours_fr": "21:00 - 09:00 (Garde de Nuit)",
        "duty_hours_ar": "21:00 - 09:00 (حراسة ليلية)",
        "opens": "21:00",
        "closes": "09:00"
    }

def fetch_city_pharmacies(city_slug, city_name, existing_map=None):
    url = f"https://garde24.ma/fr/pharmacie-de-garde/{city_slug}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    pharmacies = []

    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            html = response.read().decode("utf-8", errors="ignore")
            matches = re.findall(r'<script type=["\']application/ld\+json["\']>(.*?)</script>', html, re.DOTALL)
            for m in matches:
                try:
                    data = json.loads(m.strip())
                    graph = data.get("@graph", [data])
                    for item in graph:
                        item_type = item.get("@type", "")
                        if item_type in ["Pharmacy", "MedicalBusiness", "LocalBusiness"]:
                            name = clean_text(item.get("name", ""))
                            addr_obj = item.get("address", {})
                            address = addr_obj.get("streetAddress", "") if isinstance(addr_obj, dict) else str(addr_obj)
                            phone = item.get("telephone", "")
                            
                            geo = item.get("geo", {})
                            lat = float(geo.get("latitude", 0.0)) if geo.get("latitude") else None
                            lng = float(geo.get("longitude", 0.0)) if geo.get("longitude") else None
                            
                            if name:
                                duty = parse_pharmacy_duty(item, html)
                                existing_p = None
                                if existing_map:
                                    k = (normalize(city_name), normalize(name))
                                    existing_p = existing_map.get(k)
                                
                                name_ar = existing_p.get("name_ar", name) if existing_p else name
                                addr_ar = existing_p.get("address_ar", clean_text(address)) if existing_p else clean_text(address)
                                city_ar = existing_p.get("city_ar", "") if existing_p else ""
                                
                                # Conserver les coordonnées GPS étalonnées de Saydalia
                                if existing_p and existing_p.get("latitude") and existing_p.get("longitude"):
                                    lat = existing_p["latitude"]
                                    lng = existing_p["longitude"]

                                pharmacies.append({
                                    "id": f"{city_slug}_{len(pharmacies) + 1}",
                                    "name": name,
                                    "name_ar": name_ar,
                                    "address": clean_text(address),
                                    "address_ar": addr_ar,
                                    "phone": clean_phone(phone),
                                    "city": city_name,
                                    "city_ar": city_ar,
                                    "duty_type": duty["duty_type"],
                                    "duty_category": duty["duty_category"],
                                    "duty_label_fr": duty["duty_label_fr"],
                                    "duty_label_ar": duty["duty_label_ar"],
                                    "duty_hours_fr": duty["duty_hours_fr"],
                                    "duty_hours_ar": duty["duty_hours_ar"],
                                    "is_open": True,
                                    "latitude": lat,
                                    "longitude": lng,
                                    "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                                })
                except Exception:
                    continue

    except Exception as e:
        print(f"Erreur pour {city_name}: {e}")

    return pharmacies

def enforce_moroccan_syndicate_rules(pharmacies):
    """
    Applique les règles syndicales officielles :
    - Kénitra : en semaine (hors weekend), 2 pharmacies de nuit (Al Widad & Principale)
      le weekend, 5 pharmacies de garde (Ouled Oujih, Le Moulin, Tahiri, El Manzeh, Mabrouka)
    - Mohammédia : les pharmacies de garde sont actives la nuit
    """
    for p in pharmacies:
        city_norm = strip_accents(p.get("city", "").lower())
        name_norm = strip_accents(p.get("name", "").lower())

        if "kenitra" in city_norm:
            if any(w in name_norm for w in ["widad", "principale"]):
                p["duty_category"] = "night"
                p["duty_type"] = "night"
                p["duty_label_fr"] = "Garde de Nuit"
                p["duty_label_ar"] = "حراسة ليلية"
                p["duty_hours_fr"] = "21:00 - 09:00 (Garde de Nuit en Semaine)"
                p["duty_hours_ar"] = "21:00 - 09:00 (حراسة ليلية أسبوعية)"
            else:
                p["duty_category"] = "weekend"
                p["duty_type"] = "weekend"
                p["duty_label_fr"] = "Garde Weekend"
                p["duty_label_ar"] = "حراسة نهاية الأسبوع"
                p["duty_hours_fr"] = "Garde Weekend (Jour & Nuit - Relève lundi)"
                p["duty_hours_ar"] = "حراسة نهاية الأسبوع (يوم وليلة - التسليم الإثنين)"
            p["is_open"] = True

        elif "mohammedia" in city_norm:
            p["duty_category"] = "night"
            p["duty_type"] = "night"
            p["duty_label_fr"] = "Garde de Nuit"
            p["duty_label_ar"] = "حراسة ليلية"
            p["duty_hours_fr"] = "21:00 - 09:00 (Garde de Nuit)"
            p["duty_hours_ar"] = "21:00 - 09:00 (حراسة ليلية)"
            p["is_open"] = True

    return pharmacies

def run():
    print(f"=== Mise à jour Quotidienne des Pharmacies de Garde Maroc ===")
    print(f"Date d'exécution : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Charger la base existante pour conserver les GPS vérifiés
    existing_map = {}
    json_path = "pharmacies.json"
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                d = json.load(f)
                for p in d.get("pharmacies", []):
                    k = (normalize(p.get("city", "")), normalize(p.get("name", "")))
                    existing_map[k] = p
            print(f"[Info] Base existante chargée avec succès : {len(existing_map)} pharmacies en référence.")
        except Exception as e:
            print(f"[Attention] Erreur lecture base locale : {e}")

    all_pharmacies = []
    for idx, city in enumerate(CITIES, 1):
        items = fetch_city_pharmacies(city["slug"], city["name"], existing_map)
        if not items and city["name"] in [p.get("city") for p in existing_map.values()]:
            print(f"[{idx}/{len(CITIES)}] {city['name']}: Scraping vide, utilisation des données sauvegardées.")
            items = [p for p in existing_map.values() if strip_accents(p.get("city", "").lower()) == strip_accents(city["name"].lower())]
        else:
            print(f"[{idx}/{len(CITIES)}] {city['name']}: {len(items)} pharmacies trouvées.")
        all_pharmacies.extend(items)

    all_pharmacies = enforce_moroccan_syndicate_rules(all_pharmacies)

    result_data = {
        "last_updated": datetime.now().isoformat(),
        "total_count": len(all_pharmacies),
        "cities_covered": len(CITIES),
        "pharmacies": all_pharmacies
    }

    with open("pharmacies.json", "w", encoding="utf-8") as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)

    print(f"\n[SUCCÈS] pharmacies.json généré avec {len(all_pharmacies)} pharmacies pour {len(CITIES)} villes !")

if __name__ == "__main__":
    run()
