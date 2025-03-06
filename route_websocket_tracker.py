#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import json
import math
import time
import asyncio
import argparse
import websockets
from datetime import datetime
from shapely.geometry import Point, LineString
from shapely.ops import nearest_points

class RouteTracker:
    """Klasa do śledzenia pozycji na trasie. Wczytuje dane raz i umożliwia wielokrotne lokalizowanie."""
    
    def __init__(self, route_file, stops_file, verbose=False):
        """Inicjalizacja z plikami trasy i przystanków."""
        self.verbose = verbose
        self.print_info(f"Inicjalizacja RouteTracker z plikami: {route_file}, {stops_file}")
        
        # Wczytaj dane
        self.route_data, self.stops_data = self.load_data(route_file, stops_file)
        
        # Utwórz geometrię trasy
        self.route_line, self.calculated_length = self.build_route_line(self.route_data)
        
        # Spróbuj odczytać długość trasy z pliku summary
        self.summary_length = self.get_route_total_length(route_file)
        
        # Użyj odczytanej długości, jeśli jest dostępna, w przeciwnym razie użyj obliczonej
        self.total_route_length = self.summary_length if self.summary_length else self.calculated_length
        
        self.print_info(f"Zbudowano linię trasy o długości {self.total_route_length:.2f} m")
        if self.summary_length:
            self.print_info(f"Uwaga: Użyto długości z pliku summary ({self.summary_length:.2f} m) zamiast obliczonej ({self.calculated_length:.2f} m)")
        
        self.ready = True
        self.print_info("RouteTracker gotowy do pracy.")
    
    def print_info(self, message):
        """Wyświetla komunikat, tylko jeśli tryb gadatliwy jest włączony."""
        if self.verbose:
            print(f"[INFO] {message}")
    
    def haversine_distance(self, coord1, coord2):
        """Oblicza odległość między dwoma punktami na powierzchni Ziemi w metrach."""
        # Sprawdź poprawność współrzędnych
        if not (isinstance(coord1, (list, tuple)) and isinstance(coord2, (list, tuple))):
            return 0
        if len(coord1) < 2 or len(coord2) < 2:
            return 0
        
        try:
            lon1, lat1 = coord1
            lon2, lat2 = coord2
            
            # Upewnij się, że współrzędne są liczbami
            if not all(isinstance(x, (int, float)) for x in [lon1, lat1, lon2, lat2]):
                return 0
            
            # Zamiana stopni na radiany
            lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
            
            # Wzór haversine'a
            dlon = lon2 - lon1
            dlat = lat2 - lat1
            a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
            c = 2 * math.asin(math.sqrt(a))
            r = 6371000  # Promień Ziemi w metrach
            
            return c * r
        except Exception as e:
            self.print_info(f"Błąd podczas obliczania odległości: {e}")
            return 0
    
    def build_route_line(self, route_data):
        """Buduje linię reprezentującą całą trasę."""
        all_points = []
        segment_lengths = []
        total_distance = 0
        
        for i, way in enumerate(route_data):
            # Zakładamy, że mamy listę węzłów (nodes) zawierającą punkty (lon, lat)
            way_points = way.get("nodes", [])
            if way_points:  # Upewnij się, że są jakieś punkty
                if i > 0 and all_points and way_points and all_points[-1] == way_points[0]:
                    # Jeśli ostatni punkt poprzedniego segmentu jest taki sam jak pierwszy punkt bieżącego,
                    # pomijamy pierwszy punkt bieżącego, aby uniknąć duplikacji
                    way_points = way_points[1:]
                
                # Obliczamy długość segmentu
                segment_length = 0
                segment_start_dist = total_distance
                for j in range(len(way_points) - 1):
                    try:
                        distance = self.haversine_distance(way_points[j], way_points[j+1])
                        segment_length += distance
                    except Exception as e:
                        self.print_info(f"Błąd podczas obliczania odległości w segmencie {i}: {e}")
                
                total_distance += segment_length
                segment_lengths.append({
                    "index": i,
                    "id": way.get("id", ""),
                    "start_distance": segment_start_dist,
                    "end_distance": total_distance,
                    "length": segment_length
                })
                
                all_points.extend(way_points)
        
        # Wypisz informacje o segmentach
        self.print_info("Informacje o segmentach trasy:")
        for i, seg in enumerate(segment_lengths):
            self.print_info(f"Segment {i+1} (ID: {seg['id']}): od {seg['start_distance']:.2f} m do {seg['end_distance']:.2f} m, długość: {seg['length']:.2f} m")
        
        self.print_info(f"Całkowita obliczona długość trasy: {total_distance:.2f} m")
        
        # Sprawdź, czy mamy wystarczającą liczbę punktów
        if len(all_points) < 2:
            raise ValueError("Niewystarczająca liczba punktów do stworzenia trasy")
        
        # Sprawdź, czy punkty mają poprawne współrzędne
        valid_points = []
        for point in all_points:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                # Upewnij się, że współrzędne to liczby i nie są NaN
                if (isinstance(point[0], (int, float)) and 
                    isinstance(point[1], (int, float)) and
                    not (math.isnan(point[0]) or math.isnan(point[1]))):
                    valid_points.append(point)
        
        if len(valid_points) < 2:
            raise ValueError("Niewystarczająca liczba poprawnych punktów do stworzenia trasy")
        
        # Usuń potencjalnie zduplikowane punkty
        unique_points = []
        prev_point = None
        for point in valid_points:
            if prev_point is None or point != prev_point:
                unique_points.append(point)
                prev_point = point
        
        self.print_info(f"Zbudowano trasę złożoną z {len(unique_points)} punktów")
        
        # Utwórz geometrię trasy
        route_line = LineString(unique_points)
        
        # Zwróć zarówno linię jak i obliczoną długość
        return route_line, total_distance
    
    def load_data(self, route_file, stops_file=None):
        """Ładuje dane trasy i przystanków z plików JSON."""
        try:
            with open(route_file, 'r', encoding='utf-8') as f:
                route_data = json.load(f)
            
            stops_data = []
            if stops_file and os.path.exists(stops_file):
                with open(stops_file, 'r', encoding='utf-8') as f:
                    stops_data = json.load(f)
                
                # Sprawdź, czy to może być summary.txt zamiast pliku JSON z przystankami
                if isinstance(stops_data, dict) and "features" not in stops_data:
                    # Spróbuj załadować summary.txt jako alternatywne źródło informacji o przystankach
                    summary_file = stops_file.replace("_stops.json", "_summary.txt")
                    if os.path.exists(summary_file):
                        try:
                            self.print_info(f"Próba załadowania danych o przystankach z pliku {summary_file}")
                            with open(summary_file, 'r', encoding='utf-8') as f:
                                summary_data = f.readlines()
                            
                            # Próba wyodrębnienia informacji o przystankach z pliku summary
                            stops_from_summary = []
                            in_stops_section = False
                            current_stop = {}
                            
                            for line in summary_data:
                                line = line.strip()
                                if "Przystanki" in line:
                                    in_stops_section = True
                                    continue
                                
                                if in_stops_section and line.startswith("Stop ID:"):
                                    if current_stop:
                                        stops_from_summary.append(current_stop)
                                    current_stop = {}
                                    parts = line.split(":")
                                    if len(parts) > 1:
                                        current_stop["id"] = parts[1].strip()
                                
                                elif in_stops_section and "Odległość od początku trasy:" in line:
                                    parts = line.split(":")
                                    if len(parts) > 1:
                                        dist_part = parts[1].strip()
                                        dist_value = dist_part.split(" ")[0]  # Bierz tylko liczbę
                                        try:
                                            current_stop["dist_from_start"] = float(dist_value)
                                        except ValueError:
                                            pass
                            
                            if current_stop:
                                stops_from_summary.append(current_stop)
                            
                            if stops_from_summary:
                                self.print_info(f"Znaleziono {len(stops_from_summary)} przystanków w pliku summary")
                                stops_data = stops_from_summary
                        except Exception as e:
                            self.print_info(f"Nie udało się załadować danych z pliku summary: {e}")
            
            # Sprawdź format danych trasy
            if not isinstance(route_data, list):
                self.print_info(f"Ostrzeżenie: Dane trasy w pliku {route_file} nie są tablicą. Sprawdzam czy to może być inny format...")
                # Sprawdź, czy mamy obiekt z kluczem "features" (format GeoJSON)
                if isinstance(route_data, dict) and "features" in route_data:
                    self.print_info("Wykryto format GeoJSON, próbuję wyodrębnić dane trasy...")
                    features = route_data.get("features", [])
                    extracted_data = []
                    for feature in features:
                        if feature.get("geometry", {}).get("type") == "LineString":
                            coords = feature.get("geometry", {}).get("coordinates", [])
                            if coords:
                                extracted_data.append({
                                    "id": feature.get("properties", {}).get("id", "unknown"),
                                    "nodes": coords,
                                    "start_node": "extracted",
                                    "end_node": "extracted"
                                })
                    route_data = extracted_data
                    self.print_info(f"Wyodrębniono {len(route_data)} segmentów trasy z GeoJSON")
            
            # Sprawdź format danych przystanków
            if stops_file and not isinstance(stops_data, list):
                self.print_info(f"Ostrzeżenie: Dane przystanków w pliku {stops_file} nie są tablicą. Sprawdzam czy to może być inny format...")
                # Sprawdź, czy mamy obiekt z kluczem "features" (format GeoJSON)
                if isinstance(stops_data, dict) and "features" in stops_data:
                    self.print_info("Wykryto format GeoJSON dla przystanków, próbuję wyodrębnić dane...")
                    features = stops_data.get("features", [])
                    extracted_stops = []
                    for feature in features:
                        if feature.get("geometry", {}).get("type") == "Point":
                            coords = feature.get("geometry", {}).get("coordinates", [])
                            props = feature.get("properties", {})
                            if coords:
                                stop_data = {
                                    "id": props.get("id", "unknown"),
                                    "position": coords,
                                    "role": props.get("role", "stop"),
                                    "name": props.get("name", "Brak nazwy")  # Dodajemy nazwę przystanku
                                }
                                
                                # Sprawdź, czy są dodatkowe informacje o odległości
                                if "dist_from_start" in props:
                                    stop_data["dist_from_start"] = props["dist_from_start"]
                                elif "distance_from_start" in props:
                                    stop_data["dist_from_start"] = props["distance_from_start"]
                                
                                extracted_stops.append(stop_data)
                    stops_data = extracted_stops
                    self.print_info(f"Wyodrębniono {len(stops_data)} przystanków z GeoJSON")
            
            # Wyświetl informacje o trasie i przystankach
            self.print_info(f"Załadowano dane trasy: {len(route_data)} segmentów")
            self.print_info(f"Załadowano dane przystanków: {len(stops_data)} przystanków")
            
            return route_data, stops_data
        except FileNotFoundError:
            print(f"Błąd: Nie znaleziono pliku {route_file} lub {stops_file}")
            raise
        except json.JSONDecodeError:
            print(f"Błąd: Niepoprawny format JSON w pliku {route_file} lub {stops_file}")
            raise
        except Exception as e:
            print(f"Błąd podczas ładowania danych: {e}")
            raise

    def find_location_on_route(self, location):
        """Znajduje najbliższy punkt na trasie do podanej lokalizacji."""
        try:
            location_point = Point(location)
            
            # Sprawdź, czy geometria trasy jest poprawna
            if not self.route_line.is_valid:
                self.print_info("Ostrzeżenie: Geometria trasy jest niepoprawna. Próba naprawy...")
                route_line = self.route_line.buffer(0)  # Próba naprawy geometrii
                
                if not route_line.is_valid:
                    raise ValueError("Nie można naprawić geometrii trasy")
            
            # Zamiast używać nearest_points, które może nie działać poprawnie,
            # obliczmy odległość do każdego segmentu trasy ręcznie
            min_distance = float('inf')
            nearest_point = None
            nearest_segment_distance = 0
            total_distance = 0
            
            coords = list(self.route_line.coords)
            
            for i in range(len(coords) - 1):
                # Utwórz segment
                segment = LineString([coords[i], coords[i+1]])
                segment_length = self.haversine_distance(coords[i], coords[i+1])
                
                # Znajdź najbliższy punkt na segmencie
                p = nearest_points(location_point, segment)[1]
                
                # Oblicz odległość
                dist = location_point.distance(p)
                
                # Jeśli to najbliższy segment, zapisz informacje
                if dist < min_distance:
                    min_distance = dist
                    nearest_point = p
                    # Oblicz odległość od początku trasy do tego punktu
                    nearest_segment_distance = total_distance + segment.project(p, normalized=True) * segment_length
                
                # Dodaj długość segmentu do całkowitej odległości
                total_distance += segment_length
            
            if nearest_point is None:
                raise ValueError("Nie znaleziono najbliższego punktu na trasie")
            
            # Oblicz odległość punktu od trasy w metrach
            # Konwersja przybliżona: 1 stopień ≈ 111 km na równiku
            distance_to_route_m = min_distance * 111000
            
            self.print_info(f"Znaleziono najbliższy punkt: {nearest_point.x}, {nearest_point.y}")
            self.print_info(f"Odległość od początku trasy: {nearest_segment_distance} m")
            self.print_info(f"Odległość od trasy: {distance_to_route_m} m")
            
            return {
                "nearest_point": (nearest_point.x, nearest_point.y),
                "distance_from_start": nearest_segment_distance,
                "distance_to_route": distance_to_route_m
            }
        except Exception as e:
            self.print_info(f"Błąd podczas lokalizacji punktu na trasie: {e}")
            # Zwróć awaryjny wynik
            return {
                "nearest_point": location,
                "distance_from_start": 0,
                "distance_to_route": 0,
                "error": str(e)
            }

    def find_nearest_stops(self, current_position, current_distance):
        """Znajduje najbliższy poprzedni i następny przystanek."""
        previous_stop = None
        next_stop = None
        stops_data = self.stops_data
        
        if not stops_data:
            self.print_info("Brak danych o przystankach")
            return previous_stop, next_stop
        
        self.print_info(f"Szukanie przystanków dla pozycji oddalonej o {current_distance:.2f} m od początku trasy (długość trasy: {self.total_route_length:.2f} m)")
        self.print_info(f"Liczba przystanków do sprawdzenia: {len(stops_data)}")
        
        # Sprawdź, czy przystanki mają już informacje o odległości od początku trasy
        has_distance_info = all("dist_from_start" in stop for stop in stops_data if isinstance(stop, dict))
        
        # Sortuj przystanki według odległości od początku trasy
        stops_with_distance = []
        for stop in stops_data:
            # Sprawdź czy przystanek ma poprawnie zdefiniowaną pozycję
            stop_position = stop.get("position", None)
            if not stop_position or not isinstance(stop_position, (list, tuple)) or len(stop_position) < 2:
                self.print_info(f"Przystanek {stop.get('id', 'nieznany')} ma niepoprawną pozycję: {stop_position}")
                continue
            
            try:
                # Jeśli przystanki mają już informacje o odległości, użyj jej
                if has_distance_info and "dist_from_start" in stop:
                    stop_distance = float(stop["dist_from_start"])
                    self.print_info(f"Użyto istniejącej odległości z danych: {stop_distance:.2f} m")
                else:
                    # Oblicz odległość przystanku od początku trasy
                    stop_point = Point(stop_position)
                    stop_distance = self.route_line.project(stop_point)
                    
                    # Skoryguj błędy w odległości (czasami project() zwraca nieprawidłowe wartości)
                    if stop_distance < 0.1 or stop_distance > self.total_route_length * 1.1:
                        # Szukaj alternatywnych źródeł odległości
                        if "distance_from_start" in stop:
                            stop_distance = float(stop["distance_from_start"])
                            self.print_info(f"Użyto odległości z pliku (distance_from_start): {stop_distance:.2f} m")
                        elif "dist" in stop:
                            stop_distance = float(stop["dist"])
                            self.print_info(f"Użyto odległości z pliku (dist): {stop_distance:.2f} m")
                
                stop_data = {
                    "id": stop.get("id", ""),
                    "role": stop.get("role", "stop"),
                    "position": stop_position,
                    "distance_from_start": stop_distance,
                    "name": stop.get("name", "Brak nazwy")  # Dodajemy nazwę przystanku
                }
                
                stops_with_distance.append(stop_data)
            except Exception as e:
                self.print_info(f"Pominięto przystanek z powodu błędu: {e}")
        
        # Upewnij się, że mamy przystanki z odległościami
        if not stops_with_distance:
            self.print_info("Nie znaleziono przystanków z prawidłowymi odległościami")
            return None, None
            
        # Sortuj przystanki według odległości od początku trasy
        sorted_stops = sorted(stops_with_distance, key=lambda x: x["distance_from_start"])
        
        # Drukuj informacje o wszystkich przystankach
        self.print_info("\nInformacje o wszystkich przystankach na trasie:")
        for i, stop in enumerate(sorted_stops):
            stop_lat, stop_lon = stop["position"][1], stop["position"][0]
            stop_name = stop.get("name", "Brak nazwy")
            self.print_info(f"{i+1}. Przystanek ID: {stop['id']} - {stop_name} (lat, lon): ({stop_lat}, {stop_lon}) - odległość: {stop['distance_from_start']:.2f} m")
        
        # 1. Znajdź poprzedni przystanek (ostatni przystanek przed lub równy aktualnej pozycji)
        for i in range(len(sorted_stops) - 1, -1, -1):  # Przeszukujemy od końca do początku
            stop = sorted_stops[i]
            if stop["distance_from_start"] <= current_distance or abs(stop["distance_from_start"] - current_distance) < 1.0:
                previous_stop = stop.copy()
                previous_stop["distance_to_current"] = current_distance - stop["distance_from_start"]
                stop_name = stop.get("name", "Brak nazwy")
                self.print_info(f"Znaleziono poprzedni przystanek: ID {stop['id']} - {stop_name}, odległość: {previous_stop['distance_to_current']:.2f} m")
                break
        
        # 2. Znajdź następny przystanek (pierwszy przystanek po aktualnej pozycji)
        for stop in sorted_stops:
            if stop["distance_from_start"] > current_distance:
                next_stop = stop.copy()
                next_stop["distance_from_current"] = stop["distance_from_start"] - current_distance
                stop_name = stop.get("name", "Brak nazwy")
                self.print_info(f"Znaleziono następny przystanek: ID {stop['id']} - {stop_name}, odległość: {next_stop['distance_from_current']:.2f} m")
                break
        
        # Wyświetl informacje o znalezionych przystankach
        if previous_stop:
            prev_name = previous_stop.get("name", "Brak nazwy")
            self.print_info(f"Najbliższy poprzedni przystanek: ID {previous_stop['id']} - {prev_name}, {previous_stop['distance_to_current']:.2f} m za nami")
        else:
            self.print_info("Nie znaleziono poprzedniego przystanku - jesteśmy na początku trasy")
        
        if next_stop:
            next_name = next_stop.get("name", "Brak nazwy")
            self.print_info(f"Najbliższy następny przystanek: ID {next_stop['id']} - {next_name}, {next_stop['distance_from_current']:.2f} m przed nami")
        else:
            self.print_info("Nie znaleziono następnego przystanku - jesteśmy na końcu trasy")
        
        return previous_stop, next_stop

    def find_segment_index(self, distance_from_start):
        """Znajduje indeks segmentu, na którym znajduje się pozycja na podstawie odległości od początku trasy."""
        if not isinstance(distance_from_start, (int, float)):
            raise ValueError("Nieprawidłowy format odległości od początku trasy")
        
        target_distance = distance_from_start
        cumulative_distance = 0
        
        self.print_info(f"Szukanie segmentu dla odległości {target_distance} m od początku trasy...")
        
        for i, way in enumerate(self.route_data):
            segment_length = 0
            nodes = way.get("nodes", [])
            
            # Sprawdź, czy mamy wystarczająco dużo węzłów
            if len(nodes) < 2:
                self.print_info(f"Segment {i} (ID: {way.get('id', 'nieznany')}) ma mniej niż 2 węzły, pomijam...")
                continue
            
            # Oblicz długość segmentu
            for j in range(len(nodes) - 1):
                try:
                    node_distance = self.haversine_distance(nodes[j], nodes[j+1])
                    segment_length += node_distance
                except Exception as e:
                    self.print_info(f"Błąd podczas obliczania odległości między węzłami w segmencie {i}: {e}")
                    continue
            
            self.print_info(f"Segment {i} (ID: {way.get('id', 'nieznany')}) ma długość {segment_length} m")
            self.print_info(f"Aktualna skumulowana odległość: {cumulative_distance} m")
            self.print_info(f"Sprawdzam czy {cumulative_distance} <= {target_distance} <= {cumulative_distance + segment_length}")
            
            # Sprawdź, czy punkt jest w tym segmencie
            if cumulative_distance <= target_distance <= cumulative_distance + segment_length:
                # Oblicz dokładną pozycję w segmencie
                segment_position = target_distance - cumulative_distance
                segment_percentage = (segment_position / segment_length) * 100 if segment_length > 0 else 0
                
                self.print_info(f"Znaleziono segment! Indeks: {i}, ID: {way.get('id', 'nieznany')}")
                self.print_info(f"Pozycja w segmencie: {segment_position} m / {segment_length} m ({segment_percentage:.2f}%)")
                
                return {
                    "segment_index": i,
                    "segment_id": way.get("id", ""),
                    "distance_in_segment": segment_position,
                    "segment_percentage": segment_percentage,
                    "segment_length": segment_length,
                    "start_node": way.get("start_node", ""),
                    "end_node": way.get("end_node", "")
                }
            
            cumulative_distance += segment_length
        
        # Jeśli punkt jest poza trasą, zwróć odpowiedni segment
        if self.route_data:
            if target_distance > cumulative_distance:
                self.print_info(f"Pozycja poza trasą (za końcem) - odległość {target_distance} m > długość trasy {cumulative_distance} m")
                # Zwróć ostatni segment
                last_way = self.route_data[-1]
                last_segment_length = 0
                last_nodes = last_way.get("nodes", [])
                for j in range(len(last_nodes) - 1):
                    try:
                        last_segment_length += self.haversine_distance(last_nodes[j], last_nodes[j+1])
                    except Exception:
                        continue
                
                return {
                    "segment_index": len(self.route_data) - 1,
                    "segment_id": last_way.get("id", ""),
                    "distance_in_segment": last_segment_length,
                    "segment_percentage": 100.0,
                    "segment_length": last_segment_length,
                    "start_node": last_way.get("start_node", ""),
                    "end_node": last_way.get("end_node", ""),
                    "warning": "Pozycja poza trasą - zwrócono ostatni segment"
                }
            elif target_distance < 0:
                self.print_info(f"Pozycja poza trasą (przed początkiem) - odległość {target_distance} m < 0")
                # Zwróć pierwszy segment
                first_way = self.route_data[0]
                first_segment_length = 0
                first_nodes = first_way.get("nodes", [])
                for j in range(len(first_nodes) - 1):
                    try:
                        first_segment_length += self.haversine_distance(first_nodes[j], first_nodes[j+1])
                    except Exception:
                        continue
                
                return {
                    "segment_index": 0,
                    "segment_id": first_way.get("id", ""),
                    "distance_in_segment": 0,
                    "segment_percentage": 0.0,
                    "segment_length": first_segment_length,
                    "start_node": first_way.get("start_node", ""),
                    "end_node": first_way.get("end_node", ""),
                    "warning": "Pozycja przed trasą - zwrócono pierwszy segment"
                }
        
        self.print_info(f"Nie znaleziono segmentu dla odległości {target_distance} m")
        return None

    def get_route_total_length(self, route_file):
        """Próbuje odczytać całkowitą długość trasy z pliku summary.txt."""
        try:
            summary_file = route_file.replace("_ways_ordered.json", "_summary.txt")
            if os.path.exists(summary_file):
                with open(summary_file, 'r', encoding='utf-8') as f:
                    summary_data = f.readlines()
                
                for line in summary_data:
                    if "Całkowita długość trasy:" in line:
                        parts = line.split(":")
                        if len(parts) > 1:
                            dist_part = parts[1].strip()
                            dist_value = dist_part.split(" ")[0]  # Bierz tylko liczbę
                            try:
                                return float(dist_value)
                            except ValueError:
                                pass
        except Exception as e:
            self.print_info(f"Błąd podczas pobierania długości trasy z pliku summary: {e}")
        
        return None
    
    def locate(self, lat, lon):
        """Główna funkcja lokalizująca pojazd na trasie."""
        # Sprawdź, czy klasa jest zainicjalizowana
        if not hasattr(self, 'ready') or not self.ready:
            raise ValueError("RouteTracker nie jest gotowy. Sprawdź, czy inicjalizacja przebiegła pomyślnie.")
        
        # Zamień kolejność na [longitude, latitude] dla standardu GeoJSON
        location = (lon, lat)
        
        # Sprawdź, czy lokalizacja jest poprawnie zdefiniowana
        if not isinstance(location, (list, tuple)) or len(location) < 2:
            raise ValueError("Nieprawidłowy format lokalizacji")
        
        self.print_info(f"Lokalizowanie punktu {location} na trasie...")
        
        # Znajdź pozycję na trasie
        position_info = self.find_location_on_route(location)
        
        # Znajdź segment, na którym znajduje się pozycja
        segment_info = None
        try:
            segment_info = self.find_segment_index(position_info["distance_from_start"])
        except Exception as e:
            self.print_info(f"Błąd podczas znajdowania segmentu: {e}")
        
        # Znajdź najbliższe przystanki
        prev_stop, next_stop = self.find_nearest_stops(position_info["nearest_point"], position_info["distance_from_start"])
        
        # Oblicz procentowy postęp na trasie (uwzględniając potencjalnie skorygowaną długość)
        progress_percentage = (position_info["distance_from_start"] / self.total_route_length * 100) if self.total_route_length > 0 else 0
        
        # Przygotuj wynik
        result = {
            "location": location,
            "nearest_point_on_route": position_info["nearest_point"],
            "distance_from_start": position_info["distance_from_start"],
            "distance_to_route": position_info["distance_to_route"],
            "previous_stop": prev_stop,
            "next_stop": next_stop,
            "segment_info": segment_info,
            "total_route_length": self.total_route_length,
            "calculated_length": self.calculated_length,
            "summary_length": self.summary_length,
            "progress_percentage": progress_percentage
        }
        
        return result

class WebSocketTracker:
    """Klasa do śledzenia pojazdów za pomocą WebSocket."""
    
    def __init__(self, tracker, websocket_url, vehicle_id, update_interval=1.0, verbose=False):
        """Inicjalizacja z trackerem, URL websocketa i numerem pojazdu."""
        self.tracker = tracker
        self.websocket_url = websocket_url
        self.vehicle_id = str(vehicle_id)  # Upewnij się, że numer pojazdu jest stringiem
        self.update_interval = update_interval
        self.verbose = verbose
        self.running = False
        self.last_position = None
        self.last_result = None
        self.last_update_time = None
    
    def print_info(self, message):
        """Wyświetla komunikat, tylko jeśli tryb gadatliwy jest włączony."""
        if self.verbose:
            print(f"[INFO] {message}")
    
    def format_timestamp(self, timestamp):
        """Formatuje timestamp do czytelnej postaci."""
        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            return str(timestamp)
    
    def find_vehicle_in_data(self, message_data):
        """Znajduje pojazd o określonym numerze w danych z websocketa."""
        if not message_data or not isinstance(message_data, dict):
            self.print_info("Dane nie są obiektem JSON")
            return None
        
        # Sprawdź, czy mamy strukturę z topic i data
        if "topic" not in message_data or "data" not in message_data:
            self.print_info("Brak pola topic lub data w wiadomości")
            if self.verbose:
                self.print_info(f"Dostępne klucze w wiadomości: {list(message_data.keys())}")
            return None
        
        topic = message_data["topic"]
        data = message_data["data"]
        
        # Sprawdź, czy topic to vehicles_info
        if topic != "vehicles_info":
            self.print_info(f"Temat wiadomości to '{topic}', nie 'vehicles_info'")
            return None
        
        # Sprawdź, czy data to lista pojazdów
        if not isinstance(data, list):
            self.print_info("Dane pojazdów nie są tablicą")
            return None
        
        vehicles = data
        
        # Debugowanie - wypisz liczbę pojazdów
        self.print_info(f"Znaleziono {len(vehicles)} pojazdów w danych")
        
        # Jeśli w trybie gadatliwym, wypisz kilka pierwszych pojazdów
        if self.verbose and len(vehicles) > 0:
            sample_size = min(3, len(vehicles))
            self.print_info(f"Przykładowe pojazdy (pierwsze {sample_size}):")
            for i in range(sample_size):
                vehicle = vehicles[i]
                veh_number = vehicle.get("veh_number", "N/A")
                self.print_info(f"  - Pojazd #{i+1}: veh_number={veh_number}")
        
        # Znajdź pojazd o określonym numerze
        for vehicle in vehicles:
            if str(vehicle.get("veh_number", "")) == self.vehicle_id:
                self.print_info(f"Znaleziono pojazd o numerze {self.vehicle_id}")
                return vehicle
        
        # Nie znaleziono pojazdu - pokaż listę wszystkich dostępnych pól w pierwszym pojeździe
        if self.verbose and len(vehicles) > 0:
            self.print_info(f"Dostępne pola w pierwszym pojeździe:")
            for key in vehicles[0].keys():
                self.print_info(f"  - {key}: {vehicles[0].get(key)}")
            
            # Pokaż również wszystkie dostępne numery pojazdów
            all_numbers = [str(v.get("veh_number", "N/A")) for v in vehicles]
            self.print_info(f"Dostępne numery pojazdów: {', '.join(all_numbers)}")
        
        return None
    def extract_location(self, vehicle_data):
        """Wyciąga pozycję z danych pojazdu."""
        if not vehicle_data or not isinstance(vehicle_data, dict):
            return None
        
        # Próbuj uzyskać dane o pozycji
        try:
            latitude = float(vehicle_data.get("latitude", 0))
            longitude = float(vehicle_data.get("longitude", 0))
            
            # Sprawdź poprawność współrzędnych
            if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
                self.print_info(f"Nieprawidłowe współrzędne: ({latitude}, {longitude})")
                return None
            
            # Zwróć info o pozycji i inne przydatne dane
            return {
                "latitude": latitude,
                "longitude": longitude,
                "timestamp": vehicle_data.get("timestamp", None),
                "heading": vehicle_data.get("heading", None),
                "speed": vehicle_data.get("speed", None),
                "line": vehicle_data.get("line", None),
                "brigade": vehicle_data.get("brigade", None)
            }
        except Exception as e:
            self.print_info(f"Błąd podczas wyciągania pozycji: {e}")
            return None
    
    def pretty_print_position(self, position, result):
        """Wyświetla informacje o aktualnej pozycji pojazdu."""
        if not position or not result:
            return
        
        # Nagłówek z podstawowymi informacjami
        clear_console()
        print("\n=== ŚLEDZENIE POJAZDU ===")
        print(f"Numer pojazdu: {self.vehicle_id}")
        if "line" in position:
            print(f"Linia: {position.get('line', 'N/A')}")
        if "brigade" in position:
            print(f"Brygada: {position.get('brigade', 'N/A')}")
        if "timestamp" in position:
            print(f"Czas pomiaru: {self.format_timestamp(position.get('timestamp'))}")
        if "speed" in position:
            speed = position.get('speed', 0)
            if isinstance(speed, (int, float)):
                print(f"Prędkość: {speed:.1f} km/h")
        
        # Informacje o pozycji na trasie
        print("\n--- POZYCJA NA TRASIE ---")
        print(f"Współrzędne GPS: ({position['latitude']:.6f}, {position['longitude']:.6f})")
        print(f"Odległość od początku trasy: {result['distance_from_start']:.2f} m")
        print(f"Odległość od trasy: {result['distance_to_route']:.2f} m")
        print(f"Postęp trasy: {result['progress_percentage']:.2f}%")
        
        # Informacje o przystankach
        print("\n--- PRZYSTANKI ---")
        if result['previous_stop']:
            prev = result['previous_stop']
            prev_name = prev.get('name', 'Brak nazwy')
            print(f"Poprzedni przystanek: {prev_name}")
            print(f"  Odległość za pojazdem: {prev['distance_to_current']:.2f} m")
        else:
            print("Brak poprzedniego przystanku (początek trasy)")
        
        if result['next_stop']:
            next_s = result['next_stop']
            next_name = next_s.get('name', 'Brak nazwy')
            print(f"Następny przystanek: {next_name}")
            print(f"  Odległość przed pojazdem: {next_s['distance_from_current']:.2f} m")
        else:
            print("Brak następnego przystanku (koniec trasy)")
        
        # Postęp między przystankami
        if result['previous_stop'] and result['next_stop']:
            prev_stop = result['previous_stop']
            next_stop = result['next_stop']
            prev_name = prev_stop.get('name', 'Brak nazwy')
            next_name = next_stop.get('name', 'Brak nazwy')
            total_distance_between_stops = next_stop['distance_from_start'] - prev_stop['distance_from_start']
            current_distance_from_prev = result['distance_from_start'] - prev_stop['distance_from_start']
            progress_between_stops = (current_distance_from_prev / total_distance_between_stops * 100) if total_distance_between_stops > 0 else 0
            
            print(f"\nOdcinek: {prev_name} → {next_name}")
            print(f"Postęp na odcinku: {progress_between_stops:.2f}%")
            
            # Wizualizacja postępu na odcinku
            bar_width = 50
            filled_width = int(bar_width * progress_between_stops / 100)
            progress_bar = '█' * filled_width + '░' * (bar_width - filled_width)
            print(f"{prev_name} {progress_bar} {next_name}")
        
        # Informacja o aktualnym czasie (dla odniesienia)
        print(f"\nAktualny czas: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("Naciśnij Ctrl+C, aby zakończyć śledzenie...")
    
    def handle_position_update(self, position):
        """Obsługuje aktualizację pozycji pojazdu."""
        if not position:
            return
        
        now = time.time()
        
        # Sprawdź, czy pozycja się zmieniła
        is_new_position = (self.last_position is None or 
                          position['latitude'] != self.last_position['latitude'] or 
                          position['longitude'] != self.last_position['longitude'])
        
        # Aktualizuj tylko jeśli pozycja się zmieniła lub minęło wystarczająco dużo czasu
        if is_new_position or self.last_update_time is None or (now - self.last_update_time) >= self.update_interval:
            try:
                # Lokalizuj na trasie
                result = self.tracker.locate(position['latitude'], position['longitude'])
                
                # Wyświetl informacje
                self.pretty_print_position(position, result)
                
                # Aktualizuj ostatnie dane
                self.last_position = position
                self.last_result = result
                self.last_update_time = now
            except Exception as e:
                print(f"Błąd podczas lokalizacji pojazdu: {e}")
    
    async def start_tracking(self):
        """Rozpoczyna śledzenie pojazdu poprzez WebSocket."""
        self.running = True
        print(f"Rozpoczynam śledzenie pojazdu o numerze: {self.vehicle_id}")
        print(f"Łączę z websocketem: {self.websocket_url}")
        
        try:
            async with websockets.connect(self.websocket_url) as websocket:
                print("Połączono z websocketem. Oczekiwanie na dane...")
                
                while self.running:
                    try:
                        # Pobierz dane z websocketa
                        message = await websocket.recv()
                        
                        # Parsuj JSON
                        try:
                            data = json.loads(message)
                        except json.JSONDecodeError:
                            self.print_info("Otrzymano nieprawidłowy format JSON")
                            continue
                        
                        # Znajdź pojazd w danych
                        vehicle = self.find_vehicle_in_data(data)
                        if not vehicle:
                            self.print_info(f"Nie znaleziono pojazdu o numerze {self.vehicle_id} w danych")
                            continue
                        
                        # Wyciągnij pozycję
                        position = self.extract_location(vehicle)
                        if position:
                            # Obsłuż aktualizację pozycji
                            self.handle_position_update(position)
                        
                    except websockets.exceptions.ConnectionClosed:
                        print("Połączenie z websocketem zostało zamknięte. Próba ponownego połączenia...")
                        break
                    except Exception as e:
                        print(f"Błąd podczas przetwarzania danych: {e}")
                        await asyncio.sleep(1)
        except Exception as e:
            print(f"Błąd połączenia z websocketem: {e}")
    
    def stop_tracking(self):
        """Zatrzymuje śledzenie pojazdu."""
        self.running = False
        print("Zatrzymano śledzenie pojazdu.")

def clear_console():
    """Czyści konsolę."""
    # Dla różnych systemów operacyjnych
    os.system('cls' if os.name == 'nt' else 'clear')

def pretty_print_result(result):
    """Wyświetla wynik w czytelnej formie."""
    print("\n--- INFORMACJE O POZYCJI NA TRASIE ---")
    lat, lon = result['location'][1], result['location'][0]  # Odwrócona kolejność dla wyświetlania
    nearest_lat, nearest_lon = result['nearest_point_on_route'][1], result['nearest_point_on_route'][0]
    print(f"Aktualna lokalizacja (lat, lon): ({lat}, {lon})")
    print(f"Najbliższy punkt na trasie (lat, lon): ({nearest_lat}, {nearest_lon})")
    print(f"Odległość od początku trasy: {result['distance_from_start']:.2f} m")
    print(f"Odległość od trasy: {result['distance_to_route']:.2f} m")
    print(f"Całkowita długość trasy: {result['total_route_length']:.2f} m")
    print(f"Postęp na trasie: {result['progress_percentage']:.2f}%")
    
    # Informacje o segmencie
    if result['segment_info']:
        segment = result['segment_info']
        print("\n--- INFORMACJE O SEGMENCIE ---")
        print(f"Segment nr: {segment['segment_index'] + 1}")
        print(f"ID segmentu: {segment['segment_id']}")
        print(f"Węzeł początkowy: {segment['start_node']}")
        print(f"Węzeł końcowy: {segment['end_node']}")
        print(f"Pozycja w segmencie: {segment['distance_in_segment']:.2f} m / {segment['segment_length']:.2f} m ({segment['segment_percentage']:.2f}%)")
        if 'warning' in segment:
            print(f"UWAGA: {segment['warning']}")
    
    # Informacje o przystankach
    print("\n--- INFORMACJE O PRZYSTANKACH ---")
    
    if result['previous_stop']:
        prev = result['previous_stop']
        prev_lat, prev_lon = prev['position'][1], prev['position'][0]  # Odwrócona kolejność dla wyświetlania
        prev_name = prev.get('name', 'Brak nazwy')  # Pobierz nazwę przystanku
        print(f"Poprzedni przystanek:")
        print(f"  ID: {prev['id']}")
        print(f"  Nazwa: {prev_name}")
        print(f"  Typ: {prev['role']}")
        print(f"  Pozycja (lat, lon): ({prev_lat}, {prev_lon})")
        print(f"  Odległość od początku trasy: {prev['distance_from_start']:.2f} m")
        print(f"  Odległość za nami: {prev['distance_to_current']:.2f} m")
    else:
        print("Brak poprzedniego przystanku (jesteśmy na początku trasy)")
    
    if result['next_stop']:
        next_s = result['next_stop']
        next_lat, next_lon = next_s['position'][1], next_s['position'][0]  # Odwrócona kolejność dla wyświetlania
        next_name = next_s.get('name', 'Brak nazwy')  # Pobierz nazwę przystanku
        print(f"Następny przystanek:")
        print(f"  ID: {next_s['id']}")
        print(f"  Nazwa: {next_name}")
        print(f"  Typ: {next_s['role']}")
        print(f"  Pozycja (lat, lon): ({next_lat}, {next_lon})")
        print(f"  Odległość od początku trasy: {next_s['distance_from_start']:.2f} m")
        print(f"  Odległość przed nami: {next_s['distance_from_current']:.2f} m")
    else:
        print("Brak następnego przystanku (jesteśmy na końcu trasy)")
        
    # Podsumowanie pozycji między przystankami
    if result['previous_stop'] and result['next_stop']:
        prev_stop = result['previous_stop']
        next_stop = result['next_stop']
        prev_name = prev_stop.get('name', 'Brak nazwy')
        next_name = next_stop.get('name', 'Brak nazwy')
        total_distance_between_stops = next_stop['distance_from_start'] - prev_stop['distance_from_start']
        current_distance_from_prev = result['distance_from_start'] - prev_stop['distance_from_start']
        progress_between_stops = (current_distance_from_prev / total_distance_between_stops * 100) if total_distance_between_stops > 0 else 0
        
        print("\n--- POZYCJA POMIĘDZY PRZYSTANKAMI ---")
        print(f"Przystanki: {prev_name} → {next_name}")
        print(f"Odległość między przystankami: {total_distance_between_stops:.2f} m")
        print(f"Odległość przebyta od poprzedniego przystanku: {current_distance_from_prev:.2f} m")
        print(f"Postęp między przystankami: {progress_between_stops:.2f}%")

async def run_websocket_tracker(tracker, websocket_url, vehicle_id, update_interval=1.0, verbose=False):
    """Uruchamia śledzenie pojazdu za pomocą WebSocket."""
    ws_tracker = WebSocketTracker(tracker, websocket_url, vehicle_id, update_interval, verbose)
    
    try:
        await ws_tracker.start_tracking()
    except KeyboardInterrupt:
        print("\nPrzerwano śledzenie pojazdu.")
        ws_tracker.stop_tracking()
    except Exception as e:
        print(f"Błąd podczas śledzenia pojazdu: {e}")
        ws_tracker.stop_tracking()

def main():
    """Główna funkcja programu."""
    parser = argparse.ArgumentParser(
        description='Śledzenie pojazdów na trasie za pomocą WebSocket. Program wczytuje dane trasy raz i śledzi pozycję pojazdu w czasie rzeczywistym.',
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument('route_file', 
                        help='Ścieżka do pliku z trasą (np. relation_123456_ways_ordered.json)')
    parser.add_argument('stops_file', 
                        help='Ścieżka do pliku z przystankami (np. relation_123456_stops.json)')
    parser.add_argument('vehicle_id', 
                        help='Numer pojazdu do śledzenia (wartość pola veh_number)')
    parser.add_argument('--websocket', default='ws://172.16.20.30:9092/ws',
                        help='URL websocketa (domyślnie: ws://172.16.20.30:9092/ws)')
    parser.add_argument('--interval', type=float, default=1.0,
                        help='Interwał aktualizacji (w sekundach, domyślnie: 1.0)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Włącza tryb gadatliwy (więcej informacji diagnostycznych)')
    
    args = parser.parse_args()
    
    try:
        print("Inicjalizowanie RouteTracker...")
        tracker = RouteTracker(args.route_file, args.stops_file, args.verbose)
        print("Inicjalizacja zakończona!")
        
        print(f"Rozpoczynam śledzenie pojazdu o numerze: {args.vehicle_id}")
        print(f"WebSocket URL: {args.websocket}")
        print(f"Interwał aktualizacji: {args.interval} s")
        print("Naciśnij Ctrl+C, aby zakończyć...")
        
        # Uruchom śledzenie WebSocket
        asyncio.run(run_websocket_tracker(
            tracker=tracker,
            websocket_url=args.websocket,
            vehicle_id=args.vehicle_id,
            update_interval=args.interval,
            verbose=args.verbose
        ))
            
    except Exception as e:
        print(f"Błąd: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())