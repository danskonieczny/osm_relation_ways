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
import folium
import webbrowser
import threading
from branca.element import Figure

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

    def generate_navigation_directions(self):
        """Generuje wskazówki nawigacyjne na podstawie trasy."""
        if not self.route_data:
            return [], []
        
        # Przygotuj pełną trasę jako listę punktów
        route_points = []
        route_node_ids = []  # Zachowaj również ID węzłów dla referencji
        for way in self.route_data:
            if not route_points:
                if "nodes" in way:
                    route_points.extend(way["nodes"])
                    if "node_ids" in way:
                        route_node_ids.extend(way["node_ids"])
            else:
                # Dodaj punkty bez duplikowania ostatniego/pierwszego punktu między odcinkami
                if "nodes" in way and len(way["nodes"]) > 1:
                    route_points.extend(way["nodes"][1:])
                    if "node_ids" in way and len(way["node_ids"]) > 1:
                        route_node_ids.extend(way["node_ids"][1:])
        
        # Przygotuj punkty przystanków, jeśli są dostępne
        stop_points = []
        if self.stops_data:
            for stop in self.stops_data:
                if "position" in stop:
                    stop_points.append({
                        "position": stop["position"],
                        "name": stop.get("name", "Przystanek bez nazwy"),
                        "dist_from_start": stop.get("dist_from_start", 0),
                        "id": stop.get("id", "")
                    })
            # Sortuj przystanki według odległości od początku trasy
            stop_points.sort(key=lambda x: x["dist_from_start"])
        
        # Lista wskazówek i punktów charakterystycznych
        directions = []
        significant_points = []
        
        # Sprawdź, czy mamy przystanek na początku trasy
        has_start_stop = False
        if stop_points and stop_points[0]["dist_from_start"] < 50:  # Jeśli pierwszy przystanek jest blisko początku
            has_start_stop = True
            first_stop_name = stop_points[0]["name"]
            directions.append(f"Rozpocznij trasę na przystanku {first_stop_name}.")
        else:
            first_way = self.route_data[0]
            directions.append(f"Rozpocznij trasę w punkcie startowym (węzeł {first_way.get('start_node', 'nieznany')}).")
        
        # Znajdź pierwszy kierunek
        if len(route_points) >= 3:
            initial_bearing = self.calculate_bearing(route_points[0], route_points[2])
            directions.append(f"Kieruj się na {self.get_cardinal_direction(initial_bearing)}.")
        
        # Wykryj istotne zakręty na trasie
        last_significant_bearing = None
        if len(route_points) >= 3:
            # Ustaw początkowy kierunek jazdy
            last_significant_bearing = self.calculate_bearing(route_points[0], route_points[2])
        
        # Parametry do wykrywania zakrętów
        step_size = 10  # Krok w punktach trasy
        lookback = 10    # Ile punktów wstecz patrzymy
        lookahead = 20   # Ile punktów w przód patrzymy
        min_turn_threshold = 40  # Minimalny kąt zmiany kierunku uznawany za zakręt (w stopniach)
        
        turn_points = []
        i = lookback
        while i < len(route_points) - lookahead:
            # Sprawdź kierunek jazdy przed potencjalnym zakrętem
            pre_turn_bearing = self.calculate_bearing(route_points[i-lookback], route_points[i])
            
            # Sprawdź kierunek jazdy po potencjalnym zakręcie
            post_turn_bearing = self.calculate_bearing(route_points[i], route_points[i+lookahead])
            
            # Oblicz zmianę kierunku (skręt)
            bearing_change = (post_turn_bearing - pre_turn_bearing + 180) % 360 - 180
            
            # Jeśli jest to istotna zmiana kierunku
            if abs(bearing_change) >= min_turn_threshold:
                # Oblicz dystans od początku trasy do punktu zakrętu
                current_distance = 0
                for j in range(i):
                    if j < len(route_points) - 1:
                        current_distance += self.haversine_distance(route_points[j], route_points[j+1])
                
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
                    "instruction": f"Skręć {turn_intensity}{turn_direction}, kierując się na {self.get_cardinal_direction(post_turn_bearing)}.",
                    "node_id": route_node_ids[i] if i < len(route_node_ids) else None
                })
                
                # Przeskocz punkty, aby uniknąć wykrywania tego samego zakrętu kilka razy
                i += lookahead
                continue
            
            i += step_size
        
        # Dodaj zakręty do listy punktów charakterystycznych
        significant_points.extend(turn_points)
        
        # Dodaj przystanki do listy punktów charakterystycznych
        if self.stops_data:
            for i, stop in enumerate(stop_points):
                # Pomijamy pierwszy przystanek, jeśli był użyty jako punkt początkowy
                if has_start_stop and i == 0:
                    continue
                    
                # Sprawdź, czy to ostatni przystanek - będzie uwzględniony w instrukcji końcowej
                if i == len(stop_points) - 1 and stop["dist_from_start"] > self.total_route_length - 50:
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
                rounded_dist = self.round_to_nearest_10(dist)
                dist_formatted = f"ok. {rounded_dist} m"
            else:
                dist_formatted = f"{dist/1000:.1f} km"
                
            directions.append(f"{dist_formatted} {point['instruction']}")
        
        # Dodaj wskazówkę końcową
        if significant_points:
            last_point_distance = significant_points[-1]["distance"]
            remaining_distance = self.total_route_length - last_point_distance
            
            # Formatuj pozostałą odległość zgodnie z zasadami
            if remaining_distance < 1000:
                rounded_dist = self.round_to_nearest_10(remaining_distance)
                dist_formatted = f"ok. {rounded_dist} m"
            else:
                dist_formatted = f"{remaining_distance/1000:.1f} km"
                
            directions.append(f"{dist_formatted} kontynuuj jazdę prosto.")
        
        # Sprawdź, czy mamy przystanek na końcu trasy
        if stop_points and stop_points[-1]["dist_from_start"] > self.total_route_length - 50:
            last_stop_name = stop_points[-1]["name"]
            directions.append(f"Dotarłeś do celu - przystanek {last_stop_name}.")
        else:
            last_way = self.route_data[-1]
            directions.append(f"Dotarłeś do celu (węzeł {last_way.get('end_node', 'nieznany')}).")
        
        return directions, significant_points

    def calculate_bearing(self, point1, point2):
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

    def get_cardinal_direction(self, bearing):
        """
        Zwraca kierunek świata (N, NE, E, SE, S, SW, W, NW) dla danego azymutu.
        """
        directions = ["północ", "północny wschód", "wschód", "południowy wschód", 
                    "południe", "południowy zachód", "zachód", "północny zachód"]
        
        index = round(bearing / 45) % 8
        return directions[index]

    def round_to_nearest_10(self, value):
        """
        Zaokrągla wartość do najbliższej dziesiątki.
        Np. 456 -> 460, 412 -> 410, 65 -> 70
        """
        return int(round(value / 10) * 10)

    def update_navigation_distances(self, current_distance):
        """
        Aktualizuje odległości do charakterystycznych punktów trasy
        na podstawie aktualnej pozycji.
        
        Args:
            current_distance: Aktualna odległość od początku trasy w metrach
        
        Returns:
            Zaktualizowane wskazówki i najbliższy punkt charakterystyczny
        """
        # Jeśli nie mamy wygenerowanych wskazówek, zrób to najpierw
        if not hasattr(self, 'navigation_directions') or not hasattr(self, 'navigation_points'):
            self.navigation_directions, self.navigation_points = self.generate_navigation_directions()
        else:
            # Użyj już wygenerowanych wskazówek
            significant_points = self.navigation_points
        
        # Pobierz wygenerowane punkty
        significant_points = self.navigation_points
        
        # Znajdź najbliższy następny punkt charakterystyczny
        next_point = None
        prev_point = None
        
        # Znajdź najbliższy następny punkt
        for i, point in enumerate(significant_points):
            if point["distance"] > current_distance:
                next_point = point.copy()
                # Zaktualizuj odległość do tego punktu
                next_point["distance_to_current"] = point["distance"] - current_distance
                
                # Jeśli to nie pierwszy punkt, zapisz również poprzedni
                if i > 0:
                    prev_point = significant_points[i-1].copy()
                break
        
        # Jeśli nie znaleziono następnego punktu, jesteśmy blisko końca
        if next_point is None and significant_points:
            # Użyj ostatniego punktu
            next_point = significant_points[-1].copy()
            # Zaktualizuj odległość do końca trasy
            remaining_distance = self.total_route_length - current_distance
            next_point["distance_to_current"] = remaining_distance
            
            # Jeśli jesteśmy już za ostatnim punktem, zaktualizuj instrukcję
            if next_point["distance"] < current_distance:
                next_point["instruction"] = "Dotarłeś do celu."
        
        # Przygotuj aktualną wskazówkę
        current_instruction = "Brak wskazówek."
        if next_point:
            # Formatuj odległość zgodnie z zasadami
            dist = next_point["distance_to_current"]
            if dist < 1000:
                rounded_dist = self.round_to_nearest_10(dist)
                dist_formatted = f"ok. {rounded_dist} m"
            else:
                dist_formatted = f"{dist/1000:.1f} km"
            
            # Stwórz wskazówkę
            current_instruction = f"Za {dist_formatted}: {next_point['instruction']}"
            
            # Dodaj informację o ukończonym postępie, jeśli mamy poprzedni punkt
            if prev_point:
                progress = (current_distance - prev_point["distance"]) / (next_point["distance"] - prev_point["distance"]) * 100
                current_instruction += f"\nPostęp do następnego punktu: {progress:.1f}%"
        
        return current_instruction, next_point, significant_points

    def initialize_navigation(self):
        """Inicjalizuje nawigację, generując wskazówki i punkty charakterystyczne."""
        # Generuj wskazówki i zapisz je jako atrybuty klasy
        self.navigation_directions, self.navigation_points = self.generate_navigation_directions()
        self.print_info(f"Wygenerowano {len(self.navigation_directions)} wskazówek i {len(self.navigation_points)} punktów charakterystycznych")
        return self.navigation_directions, self.navigation_points

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
        self.map_visualizer = None
    
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
        """Wyświetla informacje o aktualnej pozycji pojazdu wraz z wskazówkami nawigacyjnymi."""
        if not position or not result:
            return
        
        # Pobierz aktualne wskazówki nawigacyjne
        current_instruction, next_point, all_points = self.tracker.update_navigation_distances(result['distance_from_start'])
        
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
        
        # Wskazówka nawigacyjna
        print("\n=== WSKAZÓWKA NAWIGACYJNA ===")
        print(current_instruction)
        
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
        
        # Nadchodzące punkty charakterystyczne
        if all_points:
            print("\n--- NADCHODZĄCE PUNKTY CHARAKTERYSTYCZNE ---")
            upcoming_count = 0
            for point in all_points:
                if point["distance"] > result['distance_from_start']:
                    dist_to_point = point["distance"] - result['distance_from_start']
                    if dist_to_point < 1000:
                        rounded_dist = self.tracker.round_to_nearest_10(dist_to_point)
                        dist_formatted = f"ok. {rounded_dist} m"
                    else:
                        dist_formatted = f"{dist_to_point/1000:.1f} km"
                    
                    point_type = "Zakręt" if point.get("type") == "turn" else "Przystanek"
                    print(f"  • {point_type} za {dist_formatted}: {point['instruction']}")
                    
                    upcoming_count += 1
                    if upcoming_count >= 3:  # Pokaż tylko 3 najbliższe punkty
                        break
        
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
                
                # Aktualizuj wizualizację na mapie
                # if self.map_visualizer:
                #     self.map_visualizer.update_vehicle_position(position, result)
                
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
        
        # Inicjalizacja nawigacji
        print("Inicjalizacja nawigacji...")
        self.tracker.initialize_navigation()
        print("Nawigacja gotowa.")
        
        # Inicjalizacja wizualizatora mapy
        # Linie zakomentowane - zgodnie z życzeniem użytkownika
        # self.map_visualizer = RouteMapVisualizer(self.tracker)
        # self.map_visualizer.start_auto_refresh(interval=5)
        
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
            # Zatrzymaj wizualizator mapy
            # if self.map_visualizer:
            #     self.map_visualizer.stop_auto_refresh()
            print("Zatrzymano śledzenie pojazdu.")

class RouteMapVisualizer:
    """Klasa do wizualizacji trasy i pojazdu na mapie."""
    
    def __init__(self, tracker, map_file_path="route_map.html", auto_open=True, auto_refresh=True):
        """
        Inicjalizacja wizualizatora.
        
        Args:
            tracker: Instancja RouteTracker zawierająca dane o trasie i przystankach
            map_file_path: Ścieżka, gdzie ma być zapisany plik HTML z mapą
            auto_open: Czy automatycznie otworzyć mapę w przeglądarce
            auto_refresh: Czy automatycznie odświeżać mapę
        """
        self.tracker = tracker
        self.map_file_path = map_file_path
        self.auto_open = auto_open
        self.auto_refresh = auto_refresh
        self.vehicle_position = None
        self.map = None
        self.vehicle_marker = None
        self.last_update_time = None
        self.running = False
        self.refresh_thread = None
        
        # Inicjalizacja mapy
        self.create_map()
    
    def create_map(self):
        """Tworzy początkową mapę z trasą i przystankami."""
        # Zbierz wszystkie punkty trasy do obliczenia centrum
        all_points = []
        for way in self.tracker.route_data:
            if "nodes" in way and way["nodes"]:
                for node in way["nodes"]:
                    # W GeoJSON kolejność to [lon, lat], ale dla folium potrzebujemy [lat, lon]
                    all_points.append((node[1], node[0]))
        
        # Jeśli nie ma punktów, użyj domyślnych współrzędnych
        if not all_points:
            center = [52.2297, 21.0122]  # Warszawa jako domyślna lokalizacja
        else:
            # Oblicz średnie współrzędne jako centrum mapy
            avg_lat = sum(p[0] for p in all_points) / len(all_points)
            avg_lon = sum(p[1] for p in all_points) / len(all_points)
            center = [avg_lat, avg_lon]
        
        # Stwórz figurę z określonymi wymiarami
        fig = Figure(height='90%', width='100%')
        
        # Utwórz mapę
        self.map = folium.Map(
            location=center,
            zoom_start=13,
            tiles='OpenStreetMap'
        )
        fig.add_child(self.map)
        
        # Dodaj trasę
        self._add_route_to_map()
        
        # Dodaj przystanki
        self._add_stops_to_map()
        
        # Zapisz mapę do pliku
        self.map.save(self.map_file_path)
        
        # Otwórz mapę w przeglądarce, jeśli opcja jest włączona
        if self.auto_open:
            webbrowser.open('file://' + os.path.abspath(self.map_file_path))
    
    def _add_route_to_map(self):
        """Dodaje linię trasy do mapy."""
        route_points = []
        
        # Zbierz wszystkie punkty trasy w jedną listę
        for way in self.tracker.route_data:
            if "nodes" in way and way["nodes"]:
                # Przekształć punkty z [lon, lat] na [lat, lon] dla folium
                segment_points = [(node[1], node[0]) for node in way["nodes"]]
                route_points.extend(segment_points)
        
        # Dodaj linię trasy
        if route_points:
            folium.PolyLine(
                route_points,
                color='blue',
                weight=5,
                opacity=0.7,
                tooltip='Trasa'
            ).add_to(self.map)
    
    def _add_stops_to_map(self):
        """Dodaje przystanki do mapy."""
        for stop in self.tracker.stops_data:
            if "position" in stop and stop["position"]:
                # Przekształć punkt z [lon, lat] na [lat, lon] dla folium
                stop_position = (stop["position"][1], stop["position"][0])
                
                # Pobierz nazwę przystanku
                stop_name = stop.get("name", "Przystanek")
                
                # Dodaj marker przystanku
                folium.Marker(
                    stop_position,
                    popup=f"<b>{stop_name}</b><br>ID: {stop.get('id', 'N/A')}<br>Odległość od początku: {stop.get('dist_from_start', 0):.2f} m",
                    tooltip=stop_name,
                    icon=folium.Icon(color='green', icon='bus', prefix='fa')
                ).add_to(self.map)
    
    def update_vehicle_position(self, position, result):
        """
        Aktualizuje pozycję pojazdu na mapie.
        
        Args:
            position: Dane o pozycji pojazdu
            result: Wynik lokalizacji z RouteTracker
        """
        if not position:
            return
        
        # Aktualizuj czas ostatniej aktualizacji
        self.last_update_time = time.time()
        
        # Zapisz pozycję pojazdu
        self.vehicle_position = {
            'latitude': position['latitude'],
            'longitude': position['longitude'],
            'heading': position.get('heading', 0),
            'speed': position.get('speed', 0),
            'line': position.get('line', 'N/A'),
            'brigade': position.get('brigade', 'N/A'),
            'timestamp': position.get('timestamp', None),
            'distance_from_start': result['distance_from_start'],
            'distance_to_route': result['distance_to_route'],
            'progress_percentage': result['progress_percentage'],
            'previous_stop': result['previous_stop'],
            'next_stop': result['next_stop'],
            'nearest_point_on_route': result['nearest_point_on_route']
        }
        
        # Zaktualizuj mapę
        self._update_map()
    
    def _create_vehicle_popup(self):
        """Tworzy zawartość popup dla markera pojazdu."""
        position = self.vehicle_position
        timestamp = datetime.fromtimestamp(position['timestamp']).strftime('%H:%M:%S') if position.get('timestamp') else 'N/A'
        
        # Przygotuj informacje o przystankach
        prev_stop_info = "Brak danych"
        next_stop_info = "Brak danych"
        
        if position.get('previous_stop'):
            prev = position['previous_stop']
            prev_name = prev.get('name', 'Brak nazwy')
            prev_stop_info = f"{prev_name} ({prev['distance_to_current']:.0f} m temu)"
        
        if position.get('next_stop'):
            next_s = position['next_stop']
            next_name = next_s.get('name', 'Brak nazwy')
            next_stop_info = f"{next_name} (za {next_s['distance_from_current']:.0f} m)"
        
        # Stwórz zawartość HTML dla popup
        popup_content = f"""
        <div style="width: 200px;">
            <h4>Pojazd: {position.get('line', 'N/A')}/{position.get('brigade', 'N/A')}</h4>
            <p><b>Czas pomiaru:</b> {timestamp}</p>
            <p><b>Prędkość:</b> {position.get('speed', 0):.1f} km/h</p>
            <p><b>Odległość od trasy:</b> {position['distance_to_route']:.1f} m</p>
            <p><b>Postęp na trasie:</b> {position['progress_percentage']:.1f}%</p>
            <hr>
            <p><b>Poprzedni przystanek:</b><br>{prev_stop_info}</p>
            <p><b>Następny przystanek:</b><br>{next_stop_info}</p>
            <p><i>Aktualizacja: {datetime.now().strftime('%H:%M:%S')}</i></p>
        </div>
        """
        return popup_content
    
    def _update_map(self):
        """Aktualizuje mapę z nową pozycją pojazdu."""
        if not self.vehicle_position:
            return
        
        # Utwórz nową mapę
        self.create_map()
        
        # Dodaj marker pojazdu
        popup_content = self._create_vehicle_popup()
        
        # Określ kolor markera na podstawie odległości od trasy
        if self.vehicle_position['distance_to_route'] < 20:
            color = 'red'  # Na trasie
        elif self.vehicle_position['distance_to_route'] < 50:
            color = 'orange'  # Blisko trasy
        else:
            color = 'darkred'  # Daleko od trasy
        
        # Dodaj marker pojazdu
        folium.Marker(
            [self.vehicle_position['latitude'], self.vehicle_position['longitude']],
            popup=folium.Popup(popup_content, max_width=300),
            tooltip=f"Pojazd {self.vehicle_position.get('line', 'N/A')}/{self.vehicle_position.get('brigade', 'N/A')}",
            icon=folium.Icon(color=color, icon='bus', prefix='fa')
        ).add_to(self.map)
        
        # Dodaj marker najbliższego punktu na trasie
        if 'nearest_point_on_route' in self.vehicle_position:
            nearest = self.vehicle_position['nearest_point_on_route']
            folium.CircleMarker(
                [nearest[1], nearest[0]],  # Zamień [lon, lat] na [lat, lon]
                radius=5,
                color='purple',
                fill=True,
                fill_color='purple',
                tooltip='Najbliższy punkt na trasie'
            ).add_to(self.map)
        
        # Zapisz mapę do pliku
        self.map.save(self.map_file_path)
    
    def start_auto_refresh(self, interval=5):
        """
        Rozpoczyna automatyczne odświeżanie mapy.
        
        Args:
            interval: Interwał odświeżania w sekundach
        """
        if not self.auto_refresh:
            return
        
        self.running = True
        
        def refresh_loop():
            while self.running:
                time.sleep(interval)
                if self.vehicle_position:
                    self._update_map()
        
        self.refresh_thread = threading.Thread(target=refresh_loop)
        self.refresh_thread.daemon = True
        self.refresh_thread.start()
    
    def stop_auto_refresh(self):
        """Zatrzymuje automatyczne odświeżanie mapy."""
        self.running = False
        if self.refresh_thread:
            self.refresh_thread.join(timeout=1.0)

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