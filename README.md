# Boligpriser

(*en.* Map the house prices in Denmark using public data.)

Kort over ejendomspriserne i Danmark.

## Struktur

- `downloader.py` - Hent data fra [Datafordeleren](https://datafordeler.dk) og gem i GeoParquet-format.
- `explorer.py` - analyse og kort over data.

## Datakilder

- [Datafordeleren](https://datafordeler.dk)
-

## Installation

Vi forudsætter, at `uv` er installeret.
Fiona og GDAL wheels er ikke tilgængeligt til Python 3.14 endnu, so vi bruger 3.13:

```
uv python pin 3.13
```

Installer pakkerne:

```
uv sync
```

## Genveje

Hent data om ejendomsvurderinger og vurderingsejendomme:

```
uv run downloader.py vur ejendomsvurdering vurderingsejendom
```

Hent data fra BBR:

```
uv run downloader.py bbr
```

## Teknologier

- `uv` bestyrer Python versioner og miljøer
- `marimo` notebooks til eksperimenter

- `gql` GraphQL klient til indlæsning af data fra http://www.datafordeler.dk
- `pyarrow` anvendes til at læse og skrive Parquet-filer

- `geopandas` til geospatial analyse
- `lonboard` til kortvisning og visualisering

## Data

### Gem skemaer i `schemas`

Jeg anbefaler at hente GraphQL skemaerne og gemme dem i `schemas` til reference:

- BBR GraphQL Schema: https://datafordeler.dk/GraphQLSchema/BBR.graphql
- VUR GraphQL Schema: https://datafordeler.dk/GraphQLSchema/VUR.graphql

### Forespørgsler skal bygges i hånden

Jeg anbefaler at skrive disse i hånden, da "Byg GraphQL Query" funktionen på Datafordeleren
ikke genererer gyldige forespørgsler hvis man spørger på sammensatte typer. Den kan kun bruges
til skitser, skemaet er den eneste reference.

Support-afdelingen hos Datafordeler anbefaler i stedet at bruge trediepartsværktøjer som
[Altair GraphQL](https://altairgraphql.dev/) til at generere gyldige forespørgsler. Fejlen i deres "Byg GraphQL Query"
er en "kendt fejl" (23 marts, 2026), og de har ikke nogen horisont for om og hvornår de retter det.

### VUR

Dette datasæt indeholder tal om ejendomsvurderingerne.

#### Vurderinger fra 2022

Vi bruger gamle vurderinger fra 2022, da der er flest af dem. Per marts 2026 er Vurderingsstyrelsen næsten halvt færdige
med 2022-sagerne, for 2024-sagerne er der kun udsendt omkring 380.000:

```
    2022-vurderinger
    
    Deklarationer udsendt til: 1.120.000 ejendomme
    Vurderinger udsendt til: 990.000 ejendomme
    Klageprocent: ca. 0,75 %

    Der skal sendes ca. 1,81 mio. 2022-vurderinger. Udsendelsestal er opgjort 16. marts 2026 (opdateres som udgangspunkt primo og medio hver måned). 
```

https://vurdst.dk/udsendelser-af-deklarationer-og-vurderinger

### Kodelisterne er ikke på første normalform

Man skal sætte sig ind i en række kodelister for at bruge systemet, f.eks.:

- VUR DK kodelister: https://confluence.sdfi.dk/pages/viewpage.action?pageId=82346523

Af en eller anden grund er mange af koderne samensatte, hvor det havde være mere naturligt
at normalisere og adskille ortogonale dimensioner, svarende til første normalform for databaser.
Det øger kompleksiteten af klientapplikationerne og skaber stærkere koblinger end nødvendigt, så
det virker som et overraskende designvalg.


### BBR

#### Kodelister
- Statuskoder, se https://teknik.bbr.dk/kodelister/0/1/0/Livscyklus (`7 - Gældende`)
