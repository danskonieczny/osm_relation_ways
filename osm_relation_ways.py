import os
import sys
import requests
import xml.etree.ElementTree as ET
import json
import geojson
from shapely.geometry import LineString, Point, mapping
import math

def analyze_route_bidirectional(raw_ways):
    """
    Analizuje trasę pod kątem możliwości dwukierunkowego łączenia odcinków.
    Sprawdza wszystkie potencjalne połączenia, niezależnie od oryginalnej orientacji odcinków.
    """
    if not raw_ways:
        return "Nie znaleziono żadnych odcinków trasy."
    
    # Zbierz wszystkie unikalne węzły
    all_nodes = set()
    for way in raw_ways:
        all_nodes.add(way["start_node"])
        all_nodes.add(way["end_node"])
    
    # Przygotuj mapę połączeń dla każdego węzła
    node_connections = {}
    for node in all_nodes:
        node_connections[node] = {"ways": []}
    
    # Dodaj informacje o wszystkich połączeniach
    for i, way in enumerate(raw_ways):
        start_node = way["start_node"]
        end_node = way["end_node"]
        
        node_connections[start_node]["ways"].append({"way_id": way["id"], "way_index": i, "connection": "start"})
        node_connections[end_node]["ways"].append({"way_id": way["id"], "way_index": i, "connection": "end"})
    
    # Analizuj każdy węzeł
    node_analysis = {}
    terminal_nodes = []  # Węzły z tylko jednym połączeniem (potencjalne końce trasy)
    junction_nodes = []  # Węzły z więcej niż dwoma połączeniami (potencjalne skrzyżowania)
    
    for node, data in node_connections.items():
        connection_count = len(data["ways"])
        node_analysis[node] = {
            "connections": connection_count,
            "ways": data["ways"]
        }
        
        if connection_count == 1:
            terminal_nodes.append(node)
        elif connection_count > 2:
            junction_nodes.append(node)
    
    # Przygotuj raport
    report = []
    report.append(f"Analiza trasy dla {len(raw_ways)} odcinków:")
    report.append(f"- Znaleziono {len(all_nodes)} unikalnych węzłów")
    
    if terminal_nodes:
        report.append(f"- Znaleziono {len(terminal_nodes)} węzłów końcowych (z tylko jednym połączeniem):")
        for node in terminal_nodes:
            ways = node_connections[node]["ways"]
            way_info = ", ".join([f"{w['way_id']} ({w['connection']})" for w in ways])
            report.append(f"  * Węzeł {node}: {way_info}")
    
    if junction_nodes:
        report.append(f"- Znaleziono {len(junction_nodes)} węzłów skrzyżowań (z więcej niż dwoma połączeniami):")
        for node in junction_nodes:
            ways = node_connections[node]["ways"]
            connection_count = len(ways)
            report.append(f"  * Węzeł {node}: {connection_count} połączeń")
            for w in ways:
                report.append(f"    - Odcinek {w['way_id']} (jako {w['connection']})")
    
    # Sprawdź, czy trasa może być ciągła
    if len(terminal_nodes) == 2:
        report.append("- Trasa wygląda na potencjalnie ciągłą, ma dokładnie 2 węzły końcowe.")
    elif len(terminal_nodes) == 0:
        report.append("- Trasa może być zamkniętą pętlą (nie ma węzłów końcowych).")
    else:
        report.append(f"- UWAGA: Trasa ma {len(terminal_nodes)} węzłów końcowych, co oznacza prawdopodobne nieciągłości.")
    
    # Szukaj nieciągłości (sprawdź czy każdy nieterminalny węzeł ma przynajmniej 2 połączenia)
    disconnected_nodes = []
    for node, data in node_analysis.items():
        if node not in terminal_nodes and data["connections"] < 2:
            disconnected_nodes.append(node)
    
    if disconnected_nodes:
        report.append(f"- WYKRYTO {len(disconnected_nodes)} węzłów z potencjalnymi nieciągłościami:")
        for node in disconnected_nodes:
            report.append(f"  * Węzeł {node}: ma tylko {node_analysis[node]['connections']} połączenie(a)")
    
    return "\n".join(report)

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

def arrange_ways_bidirectionally(raw_ways):
    """
    Układa odcinki dróg w kolejności, traktując je jako dwukierunkowe.
    Minimalizuje liczbę odwróconych odcinków, preferując zachowanie
    oryginalnej orientacji gdzie to możliwe.
    """
    if not raw_ways:
        return []
    
    # Tworzenie pomocniczej klasy dla segmentu trasy, która może być odwrócona
    class RouteSegment:
        def __init__(self, way, reversed=False):
            self.way = way
            self.reversed = reversed
            
        @property
        def start_node(self):
            return self.way["end_node"] if self.reversed else self.way["start_node"]
            
        @property
        def end_node(self):
            return self.way["start_node"] if self.reversed else self.way["end_node"]
            
        @property
        def id(self):
            return self.way["id"]
            
        def to_dict(self):
            """Zwraca słownik reprezentujący odcinek (z możliwym odwróceniem)"""
            result = self.way.copy()
            if self.reversed:
                # Zamień start i end node w zwracanym słowniku
                result["start_node"], result["end_node"] = result["end_node"], result["start_node"]
                # Odwróć także listę węzłów, jeśli istnieje
                if "nodes" in result:
                    result["nodes"] = list(reversed(result["nodes"]))
                if "node_ids" in result:
                    result["node_ids"] = list(reversed(result["node_ids"]))
                # Dodaj flagę, że ten odcinek został odwrócony
                result["reversed"] = True
            return result
    
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
    
    # Tworzymy indeksy węzłów dla szybkiego wyszukiwania
    node_connections = {}
    
    for way in route_ways:
        start_node = way["start_node"]
        end_node = way["end_node"]
        
        if start_node not in node_connections:
            node_connections[start_node] = []
        if end_node not in node_connections:
            node_connections[end_node] = []
        
        node_connections[start_node].append(way["id"])
        node_connections[end_node].append(way["id"])
    
    # Znajdź potencjalne punkty końcowe (węzły, które pojawiają się tylko raz)
    endpoints = []
    for node, ways in node_connections.items():
        if len(ways) == 1:
            endpoints.append(node)
    
    # Jeśli znaleziono dokładnie 2 punkty końcowe, użyj jednego jako początek
    start_node = None
    if len(endpoints) >= 2:
        start_node = endpoints[0]
    else:
        # W przeciwnym razie użyj węzła z najmniejszą liczbą połączeń
        nodes_by_connections = sorted(node_connections.items(), key=lambda x: len(x[1]))
        if nodes_by_connections:
            start_node = nodes_by_connections[0][0]
    
    # Jeśli nadal nie mamy punktu startowego, użyj pierwszego węzła z listy
    if start_node is None and route_ways:
        start_node = route_ways[0]["start_node"]
    
    # Przygotuj mapę id odcinka do obiektu
    way_map = {way["id"]: way for way in route_ways}
    
    # Rozpocznij budowanie trasy od punktu startowego
    ordered_segments = []
    used_way_ids = set()
    
    current_node = start_node
    
    # Ustaw preferowany kierunek dla pierwszego odcinka - staraj się używać oryginalnej orientacji
    prefer_original_orientation = True
    
    while True:
        # Znajdź odcinki łączące się z bieżącym węzłem
        connecting_ways_original = []  # Odcinki w oryginalnej orientacji
        connecting_ways_reversed = []  # Odcinki, które trzeba odwrócić
        
        for way_id in node_connections.get(current_node, []):
            if way_id not in used_way_ids:
                way = way_map[way_id]
                
                # Sprawdź, w jaki sposób odcinek łączy się z bieżącym węzłem
                if way["start_node"] == current_node:
                    # Odcinek zaczyna się w bieżącym węźle - zachowuje oryginalną orientację
                    connecting_ways_original.append(RouteSegment(way, reversed=False))
                elif way["end_node"] == current_node:
                    # Odcinek kończy się w bieżącym węźle - trzeba go odwrócić
                    connecting_ways_reversed.append(RouteSegment(way, reversed=True))
        
        # Wybierz następny segment preferując zachowanie oryginalnej orientacji
        next_segment = None
        if prefer_original_orientation and connecting_ways_original:
            next_segment = connecting_ways_original[0]
        elif connecting_ways_reversed:
            next_segment = connecting_ways_reversed[0]
        elif connecting_ways_original:
            next_segment = connecting_ways_original[0]
        
        if next_segment is None:
            break  # Nie znaleziono więcej połączeń
        
        ordered_segments.append(next_segment)
        used_way_ids.add(next_segment.id)
        
        # Przejdź do następnego węzła
        current_node = next_segment.end_node
    
    # Jeśli mamy więcej odcinków, które nie zostały użyte, tworzymy osobne łańcuchy
    chain_segments = []
    
    while len(used_way_ids) < len(route_ways):
        # Wybierz odcinek do rozpoczęcia nowego łańcucha - preferuj jeden z punktów końcowych
        start_way = None
        start_at_endpoint = False
        
        # Najpierw sprawdź, czy możemy zacząć od któregoś punktu końcowego
        for node in endpoints:
            for way_id in node_connections.get(node, []):
                if way_id not in used_way_ids:
                    way = way_map[way_id]
                    start_way = way
                    # Preferuj rozpoczęcie łańcucha od punktu początkowego odcinka
                    start_at_endpoint = (way["start_node"] == node)
                    break
            if start_way:
                break
        
        # Jeśli nie znaleziono odcinka przy punktach końcowych, wybierz dowolny nieużyty
        if not start_way:
            for way in route_ways:
                if way["id"] not in used_way_ids:
                    start_way = way
                    start_at_endpoint = False  # Nie zaczynamy od punktu końcowego
                    break
        
        if not start_way:
            break  # Nie ma więcej odcinków do dodania
        
        # Tworzymy nowy łańcuch
        current_chain = []
        
        if start_at_endpoint:
            # Jeśli zaczynamy od punktu końcowego, zachowaj oryginalną orientację
            segment = RouteSegment(start_way, reversed=False)
        else:
            # W przeciwnym razie, zaczynamy od wyboru optymalnej orientacji
            # Sprawdzamy, czy więcej odcinków łączy się z punktem końcowym czy początkowym
            end_connections = len([wid for wid in node_connections.get(start_way["end_node"], []) 
                                  if wid not in used_way_ids and wid != start_way["id"]])
            start_connections = len([wid for wid in node_connections.get(start_way["start_node"], []) 
                                    if wid not in used_way_ids and wid != start_way["id"]])
            
            # Wybierz orientację, która ma więcej przyszłych połączeń
            segment = RouteSegment(start_way, reversed=(start_connections > end_connections))
        
        current_chain.append(segment)
        used_way_ids.add(segment.id)
        current_node = segment.end_node
        
        # Kontynuuj budowanie łańcucha
        while True:
            connecting_ways = []
            
            for way_id in node_connections.get(current_node, []):
                if way_id not in used_way_ids:
                    way = way_map[way_id]
                    
                    if way["start_node"] == current_node:
                        # Preferuj zachowanie oryginalnej orientacji
                        connecting_ways.append(RouteSegment(way, reversed=False))
                    elif way["end_node"] == current_node:
                        connecting_ways.append(RouteSegment(way, reversed=True))
            
            if not connecting_ways:
                break  # Koniec łańcucha
            
            next_segment = connecting_ways[0]
            current_chain.append(next_segment)
            used_way_ids.add(next_segment.id)
            current_node = next_segment.end_node
        
        if current_chain:
            chain_segments.append(current_chain)
    
    # Próbuj połączyć główny łańcuch i dodatkowe łańcuchy
    all_chains = [ordered_segments] + chain_segments
    
    # Sortuj łańcuchy według długości (najdłuższy pierwszy)
    all_chains.sort(key=len, reverse=True)
    
    # Konsoliduj łańcuchy, próbując je połączyć
    final_chain = all_chains[0] if all_chains else []
    
    for chain in all_chains[1:]:
        # Sprawdź, czy można dołączyć ten łańcuch na początku lub końcu głównego łańcucha
        if chain and final_chain:
            chain_start = chain[0].start_node
            chain_end = chain[-1].end_node
            main_start = final_chain[0].start_node
            main_end = final_chain[-1].end_node
            
            if main_end == chain_start:
                # Łańcuch pasuje do końca głównego łańcucha
                final_chain.extend(chain)
            elif main_start == chain_end:
                # Łańcuch pasuje do początku głównego łańcucha
                final_chain = chain + final_chain
            elif main_end == chain_end:
                # Łańcuch pasuje do końca głównego łańcucha, ale musimy go odwrócić
                final_chain.extend([RouteSegment(s.way, not s.reversed) for s in reversed(chain)])
            elif main_start == chain_start:
                # Łańcuch pasuje do początku głównego łańcucha, ale musimy go odwrócić
                final_chain = [RouteSegment(s.way, not s.reversed) for s in reversed(chain)] + final_chain
            else:
                # Nie można połączyć - po prostu dodaj na końcu
                final_chain.extend(chain)
        else:
            final_chain.extend(chain)
    
    # Konwertuj segmenty na słowniki
    ordered_ways = [segment.to_dict() for segment in final_chain]
    
    # Dodaj pętle na końcu
    ordered_ways.extend(loop_ways)
    
    # Policz odwrócone odcinki
    reversed_count = sum(1 for way in ordered_ways if "reversed" in way and way["reversed"])
    
    # Sprawdź, czy nie byłoby lepiej odwrócić całą trasę
    # Jeśli większość odcinków jest odwrócona, odwróć całą trasę
    if reversed_count > len(ordered_ways) / 2:
        initial_reversed_count = reversed_count
        print(f"Wstępnie {initial_reversed_count} z {len(ordered_ways)} odcinków jest odwróconych - odwracam całą trasę dla lepszej spójności.")
        # Odwróć całą trasę (bez pętli)
        non_loop_ways = [way for way in ordered_ways if "start_node" in way and way["start_node"] != way["end_node"]]
        
        # Odwróć trasę i przełącz flagi reversed
        non_loop_ways.reverse()
        for way in non_loop_ways:
            way["start_node"], way["end_node"] = way["end_node"], way["start_node"]
            if "nodes" in way:
                way["nodes"] = list(reversed(way["nodes"]))
            if "node_ids" in way:
                way["node_ids"] = list(reversed(way["node_ids"]))
            
            # Aktualizuj flagę reversed
            if "reversed" in way:
                way["reversed"] = not way["reversed"]
            else:
                way["reversed"] = True  # Jeśli segment nie był wcześniej oznaczony jako odwrócony, to teraz jest
        
        # Połącz z pętlami
        ordered_ways = non_loop_ways + loop_ways

        reversed_count = sum(1 for way in ordered_ways if "reversed" in way and way["reversed"])
        print(f"Po odwróceniu trasy: {reversed_count} z {len(ordered_ways)} odcinków pozostaje odwróconych.")
            # Wyświetl informacje o złożonej trasie

    print(f"\nUłożono trasę składającą się z {len(ordered_ways)} odcinków.")
    if ordered_ways:
        print(f"Punkt początkowy: {ordered_ways[0]['start_node']}")
        print(f"Punkt końcowy: {ordered_ways[-1]['end_node']}")
        print(f"Liczba odwróconych odcinków: {reversed_count} z {len(ordered_ways)}")
        
    return ordered_ways

def generate_gps_directions(ordered_ways, stops=None):
    """
    Generuje wskazówki GPS na podstawie uporządkowanych odcinków trasy i przystanków.
    Analizuje kompleksowo zakręty i podaje odległości w metrach lub kilometrach,
    w zależności od wartości.
    
    Parameters:
    ordered_ways (list): Lista uporządkowanych odcinków trasy
    stops (list, optional): Lista przystanków wzdłuż trasy
    
    Returns:
    list: Lista wskazówek GPS
    """
    if not ordered_ways:
        return ["Nie znaleziono trasy."], []
    
    # Przygotuj pełną trasę jako listę punktów
    route_points = []
    route_node_ids = []  # Zachowaj również ID węzłów dla referencji
    for way in ordered_ways:
        if not route_points:
            route_points.extend(way["nodes"])
            if "node_ids" in way:
                route_node_ids.extend(way["node_ids"])
        else:
            # Dodaj punkty bez duplikowania ostatniego/pierwszego punktu między odcinkami
            route_points.extend(way["nodes"][1:])
            if "node_ids" in way:
                route_node_ids.extend(way["node_ids"][1:])
    
    # Przygotuj punkty przystanków, jeśli są dostępne
    stop_points = []
    if stops:
        for stop in stops:
            stop_points.append({
                "position": stop["position"],
                "name": stop.get("name", "Przystanek bez nazwy"),
                "dist_from_start": stop["dist_from_start"],
                "id": stop["id"]
            })
        # Sortuj przystanki według odległości od początku trasy
        stop_points.sort(key=lambda x: x["dist_from_start"])
    
    # Lista wskazówek
    directions = []
    
    # Sprawdź, czy mamy przystanek na początku trasy
    has_start_stop = False
    first_stop_name = ""
    if stop_points and stop_points[0]["dist_from_start"] < 50:  # Jeśli pierwszy przystanek jest blisko początku trasy
        has_start_stop = True
        first_stop_name = stop_points[0]["name"]
        directions.append(f"Rozpocznij trasę na przystanku {first_stop_name}.")
    else:
        directions.append(f"Rozpocznij trasę w punkcie startowym (węzeł {ordered_ways[0]['start_node']}).")
    
    # Znajdź pierwszy kierunek
    if len(route_points) >= 3:
        initial_bearing = calculate_bearing(route_points[0], route_points[2])
        directions.append(f"Kieruj się na {get_cardinal_direction(initial_bearing)}.")
    
    # Dodaj przybliżoną długość trasy
    total_distance = 0
    for way in ordered_ways:
        nodes = way["nodes"]
        for i in range(len(nodes) - 1):
            total_distance += haversine_distance(nodes[i], nodes[i+1])
    
    # Formatowanie całkowitej długości zgodnie z zasadami
    if total_distance < 1000:
        directions.append(f"Cała trasa ma długość około {round_to_nearest_10(total_distance)} m.")
    else:
        directions.append(f"Cała trasa ma długość około {total_distance/1000:.1f} km.")
    
    # Lista punktów charakterystycznych (manewry i przystanki) z odległościami
    significant_points = []
    
    # Wykryj istotne zakręty na trasie (popatrz bardziej globalnie, unikając drobnych zmian)
    last_significant_bearing = None
    if len(route_points) >= 3:
        # Ustaw początkowy kierunek jazdy
        last_significant_bearing = calculate_bearing(route_points[0], route_points[2])
    
    # Przeszukaj trasę z dużym krokiem, aby wykryć istotne zmiany kierunku
    step_size = 10  # Krok w punktach trasy - większa wartość daje bardziej "ogólne" wykrywanie zakrętów
    lookback = 10    # Ile punktów wstecz patrzymy
    lookahead = 20   # Ile punktów w przód patrzymy
    min_turn_threshold = 40  # Minimalny kąt zmiany kierunku uznawany za zakręt (w stopniach)
    
    turn_points = []
    i = lookback
    while i < len(route_points) - lookahead:
        # Sprawdź kierunek jazdy przed potencjalnym zakrętem
        pre_turn_bearing = calculate_bearing(route_points[i-lookback], route_points[i])
        
        # Sprawdź kierunek jazdy po potencjalnym zakręcie
        post_turn_bearing = calculate_bearing(route_points[i], route_points[i+lookahead])
        
        # Oblicz zmianę kierunku (skręt)
        bearing_change = (post_turn_bearing - pre_turn_bearing + 180) % 360 - 180
        
        # Jeśli jest to istotna zmiana kierunku
        if abs(bearing_change) >= min_turn_threshold:
            # Oblicz dystans od początku trasy do punktu zakrętu
            current_distance = 0
            for j in range(i):
                if j < len(route_points) - 1:
                    current_distance += haversine_distance(route_points[j], route_points[j+1])
            
            # Określ kierunek skrętu
            turn_direction = "w prawo" if bearing_change > 0 else "w lewo"
            
            # Określ intensywność skrętu
            if abs(bearing_change) > 100:
                turn_intensity = "ostro "
            elif abs(bearing_change) > 60:
                turn_intensity = ""
            else:
                turn_intensity = "lekko "
            
            # Zapisz informacje o zakręcie
            turn_points.append({
                "type": "turn",
                "index": i,
                "distance": current_distance,
                "bearing_change": bearing_change,
                "pre_bearing": pre_turn_bearing,
                "post_bearing": post_turn_bearing,
                "instruction": f"Skręć {turn_intensity}{turn_direction}, kierując się na {get_cardinal_direction(post_turn_bearing)}.",
                "node_id": route_node_ids[i] if i < len(route_node_ids) else None
            })
            
            # Przeskocz punkty, aby uniknąć wykrywania tego samego zakrętu kilka razy
            i += lookahead
            continue
        
        i += step_size
    
    # Dodaj zakręty do listy punktów charakterystycznych
    significant_points.extend(turn_points)
    
    # Dodaj przystanki do listy punktów charakterystycznych
    if stops:
        for i, stop in enumerate(stop_points):
            # Pomijamy pierwszy przystanek, jeśli był użyty jako punkt początkowy
            if has_start_stop and i == 0:
                continue
                
            # Sprawdź, czy to ostatni przystanek - będzie uwzględniony w instrukcji końcowej
            if i == len(stop_points) - 1 and stop["dist_from_start"] > total_distance - 50:
                continue
                
            significant_points.append({
                "type": "stop",
                "distance": stop["dist_from_start"],
                "name": stop["name"],
                "instruction": f"Przystanek {stop['name']}.",
                "id": stop["id"]
            })
    
    # Sortuj wszystkie punkty charakterystyczne według odległości od początku trasy
    significant_points.sort(key=lambda x: x["distance"])
    
    # Oblicz odległość od poprzedniego punktu dla każdego punktu
    for i in range(len(significant_points)):
        if i > 0:
            significant_points[i]["distance_from_last"] = significant_points[i]["distance"] - significant_points[i-1]["distance"]
        else:
            significant_points[i]["distance_from_last"] = significant_points[i]["distance"]
    
    # Generuj wskazówki na podstawie uporządkowanych punktów charakterystycznych
    for point in significant_points:
        # Formatuj odległość zgodnie z zasadami
        dist = point["distance_from_last"]
        if dist < 1000:
            rounded_dist = round_to_nearest_10(dist)
            dist_formatted = f"ok. {rounded_dist} m"
        else:
            dist_formatted = f"{dist/1000:.1f} km"
            
        directions.append(f"{dist_formatted} {point['instruction']}")
    
    # Dodaj wskazówkę końcową
    if significant_points:
        last_point_distance = significant_points[-1]["distance"]
        remaining_distance = total_distance - last_point_distance
        
        # Formatuj pozostałą odległość zgodnie z zasadami
        if remaining_distance < 1000:
            rounded_dist = round_to_nearest_10(remaining_distance)
            dist_formatted = f"ok. {rounded_dist} m"
        else:
            dist_formatted = f"{remaining_distance/1000:.1f} km"
            
        directions.append(f"{dist_formatted} kontynuuj jazdę prosto.")
    
    # Sprawdź, czy mamy przystanek na końcu trasy
    last_stop_name = ""
    if stop_points and stop_points[-1]["dist_from_start"] > total_distance - 50:
        last_stop_name = stop_points[-1]["name"]
        directions.append(f"Dotarłeś do celu - przystanek {last_stop_name}.")
    else:
        directions.append(f"Dotarłeś do celu (węzeł {ordered_ways[-1]['end_node']}).")
    
    return directions, significant_points

def round_to_nearest_10(value):
    """
    Zaokrągla wartość do najbliższej dziesiątki.
    Np. 456 -> 460, 412 -> 410, 65 -> 70
    """
    return int(round(value / 10) * 10)

def calculate_bearing(point1, point2):
    """
    Oblicza azymut (kąt) między dwoma punktami.
    Zwraca wartość w stopniach (0-359), gdzie 0 to północ, 90 to wschód, itd.
    """
    import math
    
    lon1, lat1 = point1
    lon2, lat2 = point2
    
    # Zamiana stopni na radiany
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Wzór na azymut
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    bearing = math.atan2(y, x)
    
    # Zamiana radianów na stopnie i normalizacja do zakresu 0-359
    bearing = (math.degrees(bearing) + 360) % 360
    
    return bearing

def get_cardinal_direction(bearing):
    """
    Zwraca kierunek świata (N, NE, E, SE, S, SW, W, NW) dla danego azymutu.
    """
    directions = ["północ", "północny wschód", "wschód", "południowy wschód", 
                  "południe", "południowy zachód", "zachód", "północny zachód"]
    
    index = round(bearing / 45) % 8
    return directions[index]

def format_distance(distance_meters):
    """
    Formatuje odległość zgodnie z zasadami:
    - dla odległości < 1000m: wartość w metrach zaokrąglona do najbliższej dziesiątki
    - dla odległości >= 1000m: wartość w kilometrach z jednym miejscem po przecinku
    """
    if distance_meters < 1000:
        rounded = round_to_nearest_10(distance_meters)
        return f"ok. {rounded} m"
    else:
        return f"{distance_meters/1000:.1f} km"

def export_directions_to_file(directions, output_file):
    """
    Zapisuje wskazówki GPS do pliku tekstowego.
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        for i, direction in enumerate(directions):
            f.write(f"{i+1}. {direction}\n")
    
    print(f"Wskazówki GPS zostały zapisane do pliku: {output_file}")

def export_detailed_directions(significant_points, output_file):
    """
    Zapisuje szczegółowe informacje o punktach charakterystycznych do pliku JSON.
    """
    import json
    
    # Przygotuj dane do zapisania
    for point in significant_points:
        # Usuń niepotrzebne dane, które nie mogą być zserializowane
        if "position" in point:
            point["lon"], point["lat"] = point["position"]
            del point["position"]
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(significant_points, f, ensure_ascii=False, indent=2)
    
    print(f"Szczegółowe dane o punktach charakterystycznych zostały zapisane do pliku: {output_file}")

def create_geojson(ways, stops=None, ordered_ways=None):
    """Tworzy plik GeoJSON na podstawie dróg i przystanków."""
    # Jeśli nie podano już uporządkowanych odcinków, przetworz je
    if ordered_ways is None:
        ordered_ways = arrange_ways_bidirectionally(ways)
    
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
            reversed_info = " (ODWRÓCONY)" if "reversed" in way and way["reversed"] else ""
            f.write(f"{i+1}. Way ID: {way['id']}{reversed_info} (od węzła {way['start_node']} do {way['end_node']})\n")
        
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
    
    print(analyze_route_bidirectional(raw_ways))

    # Najpierw wykonujemy jednokrotne uporządkowanie odcinków trasy
    ordered_ways = arrange_ways_bidirectionally(raw_ways)
    
    # Tworzymy GeoJSON bez przystanków
    geojson_features = []
    
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
        geojson_features.append(feature)
    
    geojson_data = geojson.FeatureCollection(geojson_features)
    
    # Obliczanie długości trasy
    route_length = calculate_route_length(ordered_ways)
    print(f"Całkowita długość trasy: {route_length:.2f} m ({route_length/1000:.1f} km)")
    
    # Lokalizowanie przystanków na trasie
    ordered_stops = []
    if stop_nodes:
        stop_types = set([stop.get("role", "stop") for stop in stop_nodes])
        print(f"Znaleziono {len(stop_nodes)} przystanków z rolami: {', '.join(stop_types)}")
        ordered_stops = locate_stops_on_route(ordered_ways, stop_nodes)
        
        # Aktualizacja GeoJSON z przystankami
        geojson_features = []
        
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
            geojson_features.append(feature)
        
        # Dodajemy przystanki jako punkty
        for i, stop in enumerate(ordered_stops):
            point = Point(stop["position"])
            
            properties = {
                "id": stop["id"],
                "type": "stop",
                "order": i,
                "role": stop.get("role", "stop"),
                "name": stop.get("name", ""),
                "dist_from_start": stop["dist_from_start"],
                "distance_from_prev": stop["distance_from_prev"],
                "distance_to_next": stop["distance_to_next"]
            }
            
            feature = geojson.Feature(
                geometry=mapping(point),
                properties=properties
            )
            geojson_features.append(feature)
        
        geojson_data = geojson.FeatureCollection(geojson_features)
    else:
        print("Nie znaleziono przystanków (role=\"stop\", \"stop_entry_only\", \"stop_exit_only\", itp.) w relacji.")
    
    # NOWE: Generowanie wskazówek GPS z odległościami
    print("\nGenerowanie wskazówek GPS...")
    directions, significant_points = generate_gps_directions(ordered_ways, ordered_stops)
    
    # Zapisywanie wskazówek do plików
    directions_file = os.path.join(output_dir, f"relation_{relation_id}_directions.txt")
    export_directions_to_file(directions, directions_file)
    
    detailed_file = os.path.join(output_dir, f"relation_{relation_id}_directions_detailed.json")
    export_detailed_directions(significant_points, detailed_file)
    
    # Zapisywanie plików
    save_files(relation_id, xml_data, raw_ways, ordered_ways, geojson_data, ordered_stops, route_length, output_dir)
    
    print(f"Dane zostały zapisane w katalogu: {output_dir}")
    print(f"Liczba znalezionych odcinków trasy z rolą=\"\": {len(raw_ways)}")
    
    # Informacja o uporządkowanej trasie
    print("\nOdcinki trasy zostały ułożone w następującej kolejności:")
    for i, way in enumerate(ordered_ways):
        reversed_info = " (ODWRÓCONY)" if "reversed" in way and way["reversed"] else ""
        print(f"{i+1}. Way ID: {way['id']}{reversed_info} (od węzła {way['start_node']} do {way['end_node']})")
    
    # Informacja o przystankach
    if ordered_stops:
        print("\nPrzystanki (od początku trasy):")
        for i, stop in enumerate(ordered_stops):
            role = stop.get("role", "stop")
            name = stop.get("name", "Bez nazwy")  # Dodajemy nazwę przystanku
            print(f"{i+1}. Stop ID: {stop['id']} (role=\"{role}\") - Nazwa: {name}")
            dist_formatted = format_distance(stop["dist_from_start"])
            prev_dist_formatted = format_distance(stop["distance_from_prev"])
            next_dist_formatted = format_distance(stop["distance_to_next"])
            print(f"   Odległość od początku trasy: {dist_formatted}")
            print(f"   Odległość od poprzedniego przystanku: {prev_dist_formatted}")
            print(f"   Odległość do następnego przystanku: {next_dist_formatted}")
    
    # Wyświetl kilka pierwszych wskazówek GPS
    print("\nPierwsze wskazówki GPS:")
    for i, direction in enumerate(directions[:5]):
        print(f"{i+1}. {direction}")
    print(f"... (łącznie {len(directions)} wskazówek, zobacz pełną listę w pliku {directions_file})")
    
    # Wyświetl informacje o istotnych punktach nawigacyjnych
    print("\nIstotnymi punktami na trasie są:")
    types_count = {"turn": 0, "stop": 0}
    for point in significant_points:
        if point["type"] in types_count:
            types_count[point["type"]] += 1
    
    print(f"- {types_count.get('turn', 0)} zakrętów")
    print(f"- {types_count.get('stop', 0)} przystanków")
    print(f"Szczegółowe informacje o tych punktach znajdziesz w pliku {detailed_file}")
            
    print(f"\nWszystkie pliki zostały zapisane w folderze: {output_dir}")
    print(f"- relation_{relation_id}.xml - pełne dane XML")
    print(f"- relation_{relation_id}_ways_raw.json - oryginalne dane odcinków")
    print(f"- relation_{relation_id}_ways_ordered.json - uporządkowane odcinki")
    print(f"- relation_{relation_id}.geojson - dane geograficzne z trasą i przystankami")
    if ordered_stops:
        print(f"- relation_{relation_id}_stops.json - dane przystanków z odległościami")
    print(f"- relation_{relation_id}_summary.txt - podsumowanie")
    print(f"- relation_{relation_id}_directions.txt - wskazówki GPS")
    print(f"- relation_{relation_id}_directions_detailed.json - szczegółowe dane o punktach nawigacyjnych")
    print("\nGotowe!")

if __name__ == "__main__":
    main()