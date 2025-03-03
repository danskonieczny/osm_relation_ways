# OSM Relation Ways Extractor

Ten projekt zawiera dwa główne skrypty:

1. `osm_relation_ways.py` - ekstraktor danych z relacji OpenStreetMap
2. `locate_on_route.py` - lokalizator pozycji na trasie

## Opis działania

### osm_relation_ways.py

Skrypt wykonuje następujące operacje:

1. Pobiera pełne dane relacji z API OpenStreetMap na podstawie podanego ID
2. Filtruje odcinki z pustą rolą (role="") - czyli elementy głównej trasy
3. Identyfikuje przystanki (role="stop", "stop_entry_only", itp.) i ich lokalizacje
4. Układa odcinki w logicznej kolejności, tworząc spójną trasę
5. Oblicza całkowitą długość trasy oraz odległości między przystankami
6. Generuje pliki wyjściowe w formacie XML, JSON i GeoJSON

### locate_on_route.py

Skrypt wykonuje następujące operacje:

1. Wczytuje wcześniej wygenerowane dane trasy i przystanków
2. Dla podanej lokalizacji GPS (lat, lon) znajduje najbliższy punkt na trasie
3. Oblicza odległość od początku trasy oraz do najbliższych przystanków
4. Określa, w którym segmencie trasy znajduje się pozycja
5. Pokazuje informacje o postępie na trasie (procentowo i w metrach)
6. Wyświetla szczegółowe informacje o aktualnej pozycji pomiędzy przystankami

## Wymagania

-   Python 3.6 lub nowszy
-   Biblioteki: requests, geojson, shapely

## Instalacja

1. Sklonuj to repozytorium:

```
git clone https://github.com/danskonieczny/osm-relation-ways.git
cd osm-relation-ways
```

2. Zainstaluj wymagane zależności:

```
pip install -r requirements.txt
```

## Użycie

### Ekstrakcja danych trasy

```
python osm_relation_ways.py <relation_id>
```

Gdzie `<relation_id>` to ID relacji OSM (np. 17444158). ID relacji można znaleźć na stronie OpenStreetMap.

### Lokalizacja na trasie

```
python locate_on_route.py <plik_trasy.json> <plik_przystanków.json> <lat> <lon> [-v]
```

Parametry:

-   `<plik_trasy.json>` - ścieżka do pliku z trasą (np. `osm_relations/nazwa_relacji/relation_17444158_ways_ordered.json`)
-   `<plik_przystanków.json>` - ścieżka do pliku z przystankami (np. `osm_relations/nazwa_relacji/relation_17444158_stops.json`)
-   `<lat>` - szerokość geograficzna (latitude) punktu do zlokalizowania
-   `<lon>` - długość geograficzna (longitude) punktu do zlokalizowania
-   `-v` - opcjonalny parametr włączający tryb gadatliwy (więcej informacji diagnostycznych)

Przykład:

```
python locate_on_route.py osm_relations/Tramwaj_2/relation_17444158_ways_ordered.json osm_relations/Tramwaj_2/relation_17444158_stops.json 53.1229 17.0324
```

## Generowane pliki

Skrypt `osm_relation_ways.py` tworzy katalog `osm_relations/[nazwa_relacji]/` zawierający:

1. `relation_[id].xml` - pełne dane XML relacji
2. `relation_[id]_ways_raw.json` - oryginalne dane odcinków przed uporządkowaniem
3. `relation_[id]_ways_ordered.json` - uporządkowane odcinki tworzące spójną trasę
4. `relation_[id]_stops.json` - dane przystanków z odległościami
5. `relation_[id].geojson` - dane geograficzne w formacie GeoJSON (trasa i przystanki)
6. `relation_[id]_summary.txt` - podsumowanie z informacjami o trasie i przystankach

## Wsparcie dla przystanków

Skrypt obsługuje różne typy przystanków występujące w relacjach OpenStreetMap:

-   `stop` - zwykły przystanek
-   `stop_entry_only` - przystanek tylko do wsiadania
-   `stop_exit_only` - przystanek tylko do wysiadania
-   `platform` - peron/platforma
-   `platform_entry_only` - platforma tylko do wsiadania
-   `platform_exit_only` - platforma tylko do wysiadania

Dla każdego przystanku obliczane są:

-   Odległość od początku trasy
-   Odległość od poprzedniego przystanku
-   Odległość do następnego przystanku

## Funkcje lokalizatora

Skrypt `locate_on_route.py` zapewnia następujące informacje o aktualnej pozycji:

### Informacje o pozycji

-   Aktualne współrzędne GPS
-   Najbliższy punkt na trasie
-   Odległość od początku trasy
-   Odległość od trasy (jeśli punkt nie leży dokładnie na trasie)
-   Całkowita długość trasy
-   Postęp na trasie (procentowo)

### Informacje o segmencie

-   Numer i ID segmentu
-   Węzły początkowe i końcowe segmentu
-   Pozycja w segmencie (w metrach i procentowo)

### Informacje o przystankach

-   Poprzedni przystanek (ID, typ, pozycja, odległości)
-   Następny przystanek (ID, typ, pozycja, odległości)
-   Odległość między najbliższymi przystankami
-   Postęp pomiędzy przystankami (procentowo)

## Licencja

Ten projekt jest udostępniany na licencji MIT. Szczegóły znajdziesz w pliku LICENSE.

## Autor

Daniel Skonieczny (@danskonieczny)

## Podziękowania

-   Dane pochodzą z OpenStreetMap, dostępnego na licencji ODbL
