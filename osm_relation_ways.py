import os
import sys
import requests
import xml.etree.ElementTree as ET
import json
import geojson
from shapely.geometry import LineString, Point, mapping
import math

def replace_polish_characters(text):
    """Zamienia polskie znaki na ich odpowiedniki bez znaków diakrytycznych."""
    replacements = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n', 'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N', 'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z'
    }
    
    for polish, latin in replacements.items():
        text = text.replace(polish, latin)
    
    return text

def sanitize_directory_name(name):
    """Czyści nazwę katalogu, aby była bezpieczna na różnych systemach operacyjnych."""
    # Zamień znaki niedozwolone w nazwach plików/katalogów na podkreślniki
    illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*', '=', '>']
    sanitized_name = name
    
    for char in illegal_chars:
        sanitized_name = sanitized_name.replace(char, '_')
    
    # Zamiana spacji na podkreślniki
    sanitized_name = sanitized_name.replace(' ', '_')
    
    # Zamiana polskich znaków na ich odpowiedniki bez znaków diakrytycznych
    sanitized_name = replace_polish_characters(sanitized_name)
    
    # Usuń ewentualne podkreślniki na początku i końcu
    sanitized_name = sanitized_name.strip('_')
    
    return sanitized_name

def extract_directory_structure(xml_data):
    """Wyciąga informacje potrzebne do utworzenia struktury katalogów z danych XML."""
    root = ET.fromstring(xml_data)
    
    network = ""
    ref = ""
    from_tag = ""
    to_tag = ""
    relation_id = ""
    
    # Znajdź dane relacji
    for relation in root.findall(".//relation"):
        relation_id = relation.get("id", "")
        for tag in relation.findall("tag"):
            if tag.get("k") == "network":
                network = tag.get("v", "")
            elif tag.get("k") == "ref":
                ref = tag.get("v", "")
            elif tag.get("k") == "from":
                from_tag = tag.get("v", "")
            elif tag.get("k") == "to":
                to_tag = tag.get("v", "")
    
    # Sanityzacja nazw
    network = sanitize_directory_name(network)
    ref = sanitize_directory_name(ref)
    from_tag = sanitize_directory_name(from_tag)
    to_tag = sanitize_directory_name(to_tag)
    
    # Jeśli nie znaleziono wszystkich potrzebnych danych, użyj domyślnych wartości
    if not network:
        network = "unknown_network"
    if not ref:
        ref = "unknown_ref"
    if not from_tag:
        from_tag = "unknown_from"
    if not to_tag:
        to_tag = "unknown_to"
    
    # Stwórz nazwę głównego folderu i podfolderu
    main_folder = network
    sub_folder = f"{ref}_{from_tag}_{to_tag}"
    
    return relation_id, main_folder, sub_folder

def haversine_distance(coord1, coord2):
    """Oblicza odległość między dwoma punktami na powierzchni Ziemi w metrach."""
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    
    # Zamiana stopni na radiany
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Wzór haversine'a
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    r = 6371000  # Promień Ziemi w metrach
    
    return c * r

def calculate_segment_length(segment):
    """Oblicza długość segmentu drogi w metrach."""
    total_length = 0
    for i in range(len(segment) - 1):
        total_length += haversine_distance(segment[i], segment[i+1])
    return total_length

def calculate_route_length(ways):
    """Oblicza całkowitą długość trasy w metrach."""
    total_length = 0
    for way in ways:
        total_length += calculate_segment_length(way["nodes"])
    return total_length

def locate_stops_on_route(ordered_ways, stop_nodes):
    """Lokalizuje przystanki na trasie i oblicza odległość od początku trasy."""
    if not stop_nodes:
        return []
        
    # Budujemy całą trasę jako listę punktów
    complete_route = []
    distance_to_node = {}  # Dystans od początku trasy do każdego węzła
    current_dist = 0
    
    for way in ordered_ways:
        for i, node in enumerate(way["nodes"]):
            if i > 0:  # Nie dodawaj dystansu dla pierwszego punktu w segmencie
                segment_length = haversine_distance(way["nodes"][i-1], node)
                current_dist += segment_length
            
            point_key = f"{node[0]},{node[1]}"
            if point_key not in distance_to_node:  # Jeśli punkt już istnieje, zachowaj pierwszy dystans
                distance_to_node[point_key] = current_dist
            
            complete_route.append(node)
    
    # Dla każdego przystanku znajdź najbliższy punkt na trasie
    for stop in stop_nodes:
        stop_point = Point(stop["position"])
        min_distance = float('inf')
        closest_idx = -1
        
        # Znajdź najbliższy punkt na trasie
        for i, route_point in enumerate(complete_route):
            route_point_geom = Point(route_point)
            distance = stop_point.distance(route_point_geom)
            
            if distance < min_distance:
                min_distance = distance
                closest_idx = i
        
        if closest_idx != -1:
            closest_point = complete_route[closest_idx]
            point_key = f"{closest_point[0]},{closest_point[1]}"
            # Ustaw odległość przystanku od początku trasy
            stop["dist_from_start"] = distance_to_node.get(point_key, 0)
    
    # Sortuj przystanki według odległości od początku trasy
    sorted_stops = sorted(stop_nodes, key=lambda x: x["dist_from_start"])
    
    # Oblicz odległości między przystankami
    for i in range(len(sorted_stops)):
        # Odległość od poprzedniego przystanku
        if i > 0:
            sorted_stops[i]["distance_from_prev"] = sorted_stops[i]["dist_from_start"] - sorted_stops[i-1]["dist_from_start"]
        else:
            sorted_stops[i]["distance_from_prev"] = 0
        
        # Odległość do następnego przystanku
        if i < len(sorted_stops) - 1:
            sorted_stops[i]["distance_to_next"] = sorted_stops[i+1]["dist_from_start"] - sorted_stops[i]["dist_from_start"]
        else:
            sorted_stops[i]["distance_to_next"] = 0  # Dla ostatniego przystanku
    
    return sorted_stops

def fetch_relation(relation_id):
    """Pobiera dane relacji OSM na podstawie ID."""
    url = f"https://api.openstreetmap.org/api/0.6/relation/{relation_id}/full"
    response = requests.get(url)
    if response.status_code != 200:
        print(f"Błąd pobierania danych: {response.status_code}")
        sys.exit(1)
    return response.text

def extract_ways_and_stops(xml_data):
    """Wyciąga dane dróg i przystanków z relacji."""
    root = ET.fromstring(xml_data)
    
    # Zbieranie wszystkich węzłów wraz z ich tagami
    nodes = {}
    node_tags = {}  # Nowy słownik do przechowywania tagów dla każdego węzła
    for node in root.findall(".//node"):
        node_id = node.get("id")
        lat = float(node.get("lat"))
        lon = float(node.get("lon"))
        nodes[node_id] = (lon, lat)  # GeoJSON używa (długość, szerokość)
        
        # Zbieramy tagi dla tego węzła
        tags = {}
        for tag in node.findall("tag"):
            tags[tag.get("k")] = tag.get("v")
        if tags:  # Przechowujemy tagi tylko jeśli istnieją
            node_tags[node_id] = tags
    
    # Słownik do przechowywania informacji o rolach elementów w relacji
    member_roles = {}
    stop_nodes = []
    
    # Pobierz informacje o rolach elementów w relacji
    for relation in root.findall(".//relation"):
        for member in relation.findall("member"):
            if member.get("type") == "way":
                way_id = member.get("ref")
                role = member.get("role", "")
                member_roles[way_id] = role
            elif member.get("type") == "node" and member.get("role") in ["stop", "stop_entry_only", "stop_exit_only", "platform", "platform_entry_only", "platform_exit_only"]:
                stop_node_ref = member.get("ref")
                if stop_node_ref in nodes:
                    # Zapisz pozycję, ID, rolę i nazwę przystanku
                    stop_info = {
                        "id": stop_node_ref,
                        "position": nodes[stop_node_ref],
                        "role": member.get("role", ""),
                        "dist_from_start": 0  # To będzie obliczone później
                    }
                    
                    # Dodaj nazwę przystanku, jeśli jest dostępna
                    if stop_node_ref in node_tags and "name" in node_tags[stop_node_ref]:
                        stop_info["name"] = node_tags[stop_node_ref]["name"]
                    
                    stop_nodes.append(stop_info)
    
    # Zbieranie dróg z zachowaniem oryginalnej kolejności
    # Uwzględniamy TYLKO elementy z pustą rolą (role="")
    raw_ways = []
    for way in root.findall(".//way"):
        way_id = way.get("id")
        
        # Sprawdź, czy ta droga ma pustą rolę w relacji
        if way_id in member_roles and member_roles[way_id] == "":
            way_nodes = []
            way_node_ids = []
            
            for nd in way.findall("nd"):
                ref = nd.get("ref")
                if ref in nodes:
                    way_nodes.append(nodes[ref])
                    way_node_ids.append(ref)
            
            if len(way_nodes) >= 2:  # Droga musi mieć co najmniej 2 punkty
                raw_ways.append({
                    "id": way_id,
                    "nodes": way_nodes,
                    "node_ids": way_node_ids,
                    "start_node": way_node_ids[0],
                    "end_node": way_node_ids[-1]
                })
    
    return raw_ways, stop_nodes

def arrange_ways_in_order(raw_ways):
    """Układa odcinki dróg w kolejności, aby tworzyły spójną trasę."""
    if not raw_ways:
        return []
    
    # Filtrujemy tylko odcinki, które nie są pętlami
    route_ways = []
    loop_ways = []
    
    for way in raw_ways:
        if way["start_node"] == way["end_node"]:
            loop_ways.append(way)
        else:
            route_ways.append(way)
    
    if not route_ways:
        return raw_ways  # Jeśli nie ma głównych odcinków trasy, zwróć wszystkie
    
    # Tworzenie słownika węzłów końcowych do odcinków
    end_to_ways = {}
    start_to_ways = {}
    
    for i, way in enumerate(route_ways):
        start_node = way["start_node"]
        end_node = way["end_node"]
        
        if start_node not in start_to_ways:
            start_to_ways[start_node] = []
        start_to_ways[start_node].append(i)
        
        if end_node not in end_to_ways:
            end_to_ways[end_node] = []
        end_to_ways[end_node].append(i)
    
    # Znajdowanie potencjalnego początku trasy
    # Początek to węzeł, który jest punktem początkowym jakiegoś odcinka, 
    # ale nie jest punktem końcowym żadnego innego odcinka lub występuje rzadziej jako końcowy
    potential_starts = []
    for node in start_to_ways:
        if node not in end_to_ways:
            potential_starts.append((node, 999))  # Wysoki priorytet dla węzłów, które są tylko startowe
        else:
            # Jeśli węzeł występuje częściej jako początkowy niż końcowy
            if len(start_to_ways[node]) > len(end_to_ways[node]):
                potential_starts.append((node, len(start_to_ways[node]) - len(end_to_ways[node])))
    
    # Sortuj potencjalne początki wg priorytetu (malejąco)
    potential_starts.sort(key=lambda x: x[1], reverse=True)
    
    ordered_ways = []
    used_indices = set()
    
    # Próbujemy zbudować spójną trasę
    if potential_starts:
        current_node = potential_starts[0][0]  # Bierzemy węzeł o najwyższym priorytecie
        
        # Budujemy główną trasę od początku do końca
        while True:
            # Szukamy odcinka, który zaczyna się od current_node i nie był jeszcze użyty
            next_way_index = None
            for i in start_to_ways.get(current_node, []):
                if i not in used_indices:
                    next_way_index = i
                    break
            
            if next_way_index is None:
                break  # Nie znaleźliśmy pasującego odcinka, kończymy główną trasę
            
            ordered_ways.append(route_ways[next_way_index])
            used_indices.add(next_way_index)
            current_node = route_ways[next_way_index]["end_node"]
    
    # Dodajemy pozostałe odcinki główne, które nie zostały jeszcze dodane
    for i, way in enumerate(route_ways):
        if i not in used_indices:
            ordered_ways.append(way)
    
    # Dodajemy pętle na końcu
    ordered_ways.extend(loop_ways)
    
    return ordered_ways

def create_geojson(ways, stops=None):
    """Tworzy plik GeoJSON na podstawie dróg i przystanków."""
    # Najpierw układamy drogi w odpowiedniej kolejności
    ordered_ways = arrange_ways_in_order(ways)
    
    features = []
    
    # Dodajemy informację o oryginalnej kolejności dróg
    for i, way in enumerate(ordered_ways):
        line = LineString(way["nodes"])
        
        # Podstawowe właściwości
        properties = {
            "id": way["id"],
            "type": "route_segment",
            "order": i,
            "start_node": way["start_node"],
            "end_node": way["end_node"]
        }
        
        feature = geojson.Feature(
            geometry=mapping(line),
            properties=properties
        )
        features.append(feature)
    
    # Dodajemy przystanki jako punkty (jeśli są)
    if stops:
        for i, stop in enumerate(stops):
            point = Point(stop["position"])
            
            properties = {
                "id": stop["id"],
                "type": "stop",
                "order": i,
                "role": stop.get("role", "stop"),
                "name": stop.get("name", ""),  # Dodajemy nazwę przystanku
                "dist_from_start": stop["dist_from_start"],
                "distance_from_prev": stop["distance_from_prev"],
                "distance_to_next": stop["distance_to_next"]
            }
            
            feature = geojson.Feature(
                geometry=mapping(point),
                properties=properties
            )
            features.append(feature)
    
    return geojson.FeatureCollection(features), ordered_ways

def save_files(relation_id, xml_data, raw_ways, ordered_ways, geojson_data, stops_data, route_length, output_dir):
    """Zapisuje wszystkie pliki wyjściowe."""
    # Tworzenie katalogu głównego jeśli nie istnieje
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Zapisanie pliku XML
    with open(os.path.join(output_dir, f"relation_{relation_id}.xml"), "w", encoding="utf-8") as f:
        f.write(xml_data)
    
    # Zapisanie pliku JSON z oryginalnymi drogami
    with open(os.path.join(output_dir, f"relation_{relation_id}_ways_raw.json"), "w", encoding="utf-8") as f:
        json.dump(raw_ways, f, ensure_ascii=False, indent=2)
    
    # Zapisanie pliku JSON z uporządkowanymi drogami
    with open(os.path.join(output_dir, f"relation_{relation_id}_ways_ordered.json"), "w", encoding="utf-8") as f:
        json.dump(ordered_ways, f, ensure_ascii=False, indent=2)
    
    # Zapisanie pliku GeoJSON
    with open(os.path.join(output_dir, f"relation_{relation_id}.geojson"), "w", encoding="utf-8") as f:
        geojson.dump(geojson_data, f, ensure_ascii=False, indent=2)
    
    # Zapisanie pliku JSON z przystankami
    if stops_data:
        with open(os.path.join(output_dir, f"relation_{relation_id}_stops.json"), "w", encoding="utf-8") as f:
            json.dump(stops_data, f, ensure_ascii=False, indent=2)
    
    # Zapisanie prostego pliku z podsumowaniem
    with open(os.path.join(output_dir, f"relation_{relation_id}_summary.txt"), "w", encoding="utf-8") as f:
        f.write(f"Relacja: {relation_id}\n")
        f.write(f"Liczba odcinków trasy: {len(ordered_ways)}\n")
        f.write(f"Całkowita długość trasy: {route_length:.2f} m ({route_length/1000:.2f} km)\n\n")
        
        f.write("Odcinki trasy (kolejność):\n")
        for i, way in enumerate(ordered_ways):
            f.write(f"{i+1}. Way ID: {way['id']} (od węzła {way['start_node']} do {way['end_node']})\n")
        
        if stops_data:
            f.write("\nPrzystanki (od początku trasy):\n")
            for i, stop in enumerate(stops_data):
                role_text = stop.get("role", "stop")
                name_text = stop.get("name", "Bez nazwy")  # Dodajemy nazwę przystanku
                f.write(f"{i+1}. Stop ID: {stop['id']} (role=\"{role_text}\") - Nazwa: {name_text}\n")
                f.write(f"   Odległość od początku trasy: {stop['dist_from_start']:.2f} m ({stop['dist_from_start']/1000:.2f} km)\n")
                f.write(f"   Odległość od poprzedniego przystanku: {stop['distance_from_prev']:.2f} m ({stop['distance_from_prev']/1000:.2f} km)\n")
                f.write(f"   Odległość do następnego przystanku: {stop['distance_to_next']:.2f} m ({stop['distance_to_next']/1000:.2f} km)\n")

def main():
    if len(sys.argv) != 2:
        print("Użycie: python osm_relation_ways.py <relation_id>")
        sys.exit(1)
    
    relation_id = sys.argv[1]
    print(f"Pobieranie relacji {relation_id}...")
    
    # Pobieranie danych relacji
    xml_data = fetch_relation(relation_id)
    
    # Wyciąganie informacji o strukturze katalogów
    relation_id, main_folder, sub_folder = extract_directory_structure(xml_data)
    print(f"Struktura katalogów: {main_folder}/{sub_folder}")
    
    # Tworzenie struktury katalogów
    base_dir = "osm_relations"
    main_dir = os.path.join(base_dir, main_folder)
    output_dir = os.path.join(main_dir, sub_folder)
    
    # Tworzenie katalogu bazowego, jeśli nie istnieje
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    
    # Tworzenie katalogu głównego dla sieci
    if not os.path.exists(main_dir):
        os.makedirs(main_dir)
    
    # Tworzenie katalogu dla konkretnej relacji
    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
    except Exception as e:
        print(f"Błąd podczas tworzenia katalogu: {e}")
        fallback_name = f"relation_{relation_id}"
        output_dir = os.path.join(main_dir, fallback_name)
        print(f"Używanie alternatywnej nazwy katalogu: {fallback_name}")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
    
    # Przetwarzanie danych
    raw_ways, stop_nodes = extract_ways_and_stops(xml_data)
    
    if not raw_ways:
        print(f"Nie znaleziono elementów z pustą rolą (role=\"\") w relacji {relation_id}.")
        print("Sprawdź, czy relacja zawiera elementy typu 'way' z pustą rolą.")
        sys.exit(1)
    
    # Tworzenie GeoJSON i porządkowanie odcinków
    geojson_data, ordered_ways = create_geojson(raw_ways, None)  # Najpierw bez przystanków
    
    # Obliczanie długości trasy
    route_length = calculate_route_length(ordered_ways)
    print(f"Całkowita długość trasy: {route_length:.2f} m ({route_length/1000:.2f} km)")
    
    # Lokalizowanie przystanków na trasie
    if stop_nodes:
        stop_types = set([stop.get("role", "stop") for stop in stop_nodes])
        print(f"Znaleziono {len(stop_nodes)} przystanków z rolami: {', '.join(stop_types)}")
        ordered_stops = locate_stops_on_route(ordered_ways, stop_nodes)
        
        # Aktualizacja GeoJSON z przystankami
        geojson_data, _ = create_geojson(raw_ways, ordered_stops)
    else:
        print("Nie znaleziono przystanków (role=\"stop\", \"stop_entry_only\", \"stop_exit_only\", itp.) w relacji.")
        ordered_stops = []
    
    # Zapisywanie plików
    save_files(relation_id, xml_data, raw_ways, ordered_ways, geojson_data, ordered_stops, route_length, output_dir)
    
    print(f"Dane zostały zapisane w katalogu: {output_dir}")
    print(f"Liczba znalezionych odcinków trasy z rolą=\"\": {len(raw_ways)}")
    
    # Informacja o uporządkowanej trasie
    print("\nOdcinki trasy zostały ułożone w następującej kolejności:")
    for i, way in enumerate(ordered_ways):
        print(f"{i+1}. Way ID: {way['id']} (od węzła {way['start_node']} do {way['end_node']})")
    
    # Informacja o przystankach
    if ordered_stops:
        print("\nPrzystanki (od początku trasy):")
        for i, stop in enumerate(ordered_stops):
            role = stop.get("role", "stop")
            name = stop.get("name", "Bez nazwy")  # Dodajemy nazwę przystanku
            print(f"{i+1}. Stop ID: {stop['id']} (role=\"{role}\") - Nazwa: {name}")
            print(f"   Odległość od początku trasy: {stop['dist_from_start']:.2f} m")
            print(f"   Odległość od poprzedniego przystanku: {stop['distance_from_prev']:.2f} m")
            print(f"   Odległość do następnego przystanku: {stop['distance_to_next']:.2f} m")
            
    print(f"\nWszystkie pliki zostały zapisane w folderze: {output_dir}")
    print(f"- relation_{relation_id}.xml - pełne dane XML")
    print(f"- relation_{relation_id}_ways_raw.json - oryginalne dane odcinków")
    print(f"- relation_{relation_id}_ways_ordered.json - uporządkowane odcinki")
    print(f"- relation_{relation_id}.geojson - dane geograficzne z trasą i przystankami")
    if ordered_stops:
        print(f"- relation_{relation_id}_stops.json - dane przystanków z odległościami")
    print(f"- relation_{relation_id}_summary.txt - podsumowanie")
    print("\nGotowe!")

if __name__ == "__main__":
    main()