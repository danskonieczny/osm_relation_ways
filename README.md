# OSM Relation Ways Extractor

Ten skrypt pozwala na wyodrębnienie i uporządkowanie odcinków dróg (ways) z relacji OpenStreetMap. Jego główne zastosowanie to generowanie tras dla linii komunikacji miejskiej (np. tramwajów, autobusów).

## Opis działania

Skrypt wykonuje następujące operacje:
1. Pobiera pełne dane relacji z API OpenStreetMap na podstawie podanego ID
2. Filtruje odcinki z pustą rolą (role="") - czyli elementy głównej trasy
3. Układa odcinki w logicznej kolejności, tworząc spójną trasę
4. Generuje pliki wyjściowe w formacie XML, JSON i GeoJSON

## Wymagania

- Python 3.6 lub nowszy
- Biblioteki: requests, geojson, shapely

## Instalacja

1. Sklonuj to repozytorium:
```
git clone https://github.com/twój-użytkownik/osm-relation-ways.git
cd osm-relation-ways
```

2. Zainstaluj wymagane zależności:
```
pip install -r requirements.txt
```

## Użycie

Skrypt uruchamia się z linii poleceń, podając ID relacji OSM jako parametr:

```
python osm_relation_ways.py 17444158
```

Gdzie `17444158` to przykładowe ID relacji. ID relacji można znaleźć na stronie OpenStreetMap.

## Generowane pliki

Skrypt tworzy katalog `osm_relations/[nazwa_relacji]/` zawierający:

1. `relation_[id].xml` - pełne dane XML relacji
2. `relation_[id]_ways_raw.json` - oryginalne dane odcinków przed uporządkowaniem
3. `relation_[id]_ways_ordered.json` - uporządkowane odcinki tworzące spójną trasę
4. `relation_[id].geojson` - dane geograficzne w formacie GeoJSON
5. `relation_[id]_summary.txt` - podsumowanie z informacjami o trasie

## Uwagi

- Skrypt uwzględnia tylko elementy z pustą rolą (role=""), pomijając elementy takie jak platformy czy przystanki
- Algorytm sortowania stara się znaleźć logiczną kolejność odcinków, łącząc punkty końcowe z początkowymi kolejnych segmentów
- W niektórych przypadkach może być konieczne ręczne poprawienie kolejności odcinków, jeśli trasa jest skomplikowana

## Licencja

Ten projekt jest udostępniany na licencji MIT. Szczegóły znajdziesz w pliku LICENSE.

## Autor

[Daniel/skoniecznydaniel]

## Podziękowania

- Dane pochodzą z OpenStreetMap, dostępnego na licencji ODbL