# Boligpriser

(*en.* Map the house prices in Denmark using public data.)

Kort over priserne på på villaer og ejerlejligheder i Danmark.

## Struktur

- `downloader.py` - Hent data fra [Datafordeleren](https://datafordeler.dk) og gem i GeoParquet-format.
- `explorer.py` - analyse og kort over data.
- `data/` - Parquet-filer med de data vi har hentet fra Datafordeleren.
- `notebooks/` - Marimo eksperimenter med API, data og visualisering.
- `schemas/` - GraphQL-skemaer fra Datafordeleren.

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
uv run downloader.py vur ejendomsvurdering 
uv run downloader.py vur vurderingsejendom 
uv run downloader.py vur bfekrydsreference
uv run downloader.py vur grundvaerdispecifikation 
```

Hent data fra BBR:

```
uv run downloader.py bbr bygning
uv run downloader.py bbr ejendomsrelation
```

## Teknologier

- `uv` bestyrer Python versioner og miljøer
- `marimo` notebooks til eksperimenter

- `gql` GraphQL klient til indlæsning af data fra http://www.datafordeler.dk
- `pyarrow` anvendes til at læse og skrive Parquet-filer

- `geopandas` til geospatial analyse
- `lonboard` til kortvisning og visualisering

## Data

### Generelle betragninger om data

Helt generelt er data i Datafordeleren en værre rodebutik.

#### Manglende domænemodel

APIet er lige blevet modernisere, men lader til at have fokuseret på det rent tekniske aspekt at introducere
GraphQL for alle datakilder. Det lader ikke til, at moderniseringen har været rettet mod at skabe et idiomatisk
GraphQL-API eller udstiller data i en sammenhængende domænemodel, der skjuler midlertidige implementeringsdetaljer og
understøtter de almindelige anvendelser på enkel vis.

#### GraphQL uden Graph

Eksempler på dette er, at Datafordeleren har mange forskellige GraphQL-skemaer i stedet for et enkelt skema med en
sammenhængende graf. Selv i de enkelte GraphQL-skemaer mangler grafen mellem entiteterne. Man kan sige det er "GraphQL"
uden "Graph".

Konkret betyder det, at klientapplikationer selv skal lave `join` operationer, enten ved at hente alle data og gøre det
lokalt, eller over API'et, hvilket giver det velkendte *1+N* problem.

##### Initiativet Fleksibel Opslagslogik vil råde bod på dette

Problemet lader til at være kendt og der lader til at være et igangværende initiativ om at udstille relationerne i
GraphQL. Pudsigt nok udstilles det i nye separate skemaer i stedet for at sætte dem ind i de eksisterende skemaer, 
hvor man har brug for relationerne:

https://confluence.sdfi.dk/display/DML/Fleksibel+opslagslogik

Vær endvidere opmærksom på, at der er flere forskellige skemaer for samme data, der er to forskellige
bitemporalitetsmodeller, som har fået hvert sit skema, se `flexible` og `flexibleCurrent` i ovenstående.

Fleksibel opslagslogik lader ikke til at være færdig, så vi vil ikke bruge det her.

### Dataindsamling

Her anvender vi GraphQL til at hente data fra Datafordeleren til lokale Parquet filer,
hvorfra vi siden sammenstykker de relevante data.

Det tager lidt tid at hente alle data, da APIet typisk kun udleverer en side med 1000 datapunkter pr. HTTP-kald.
Det er en engangsforteelse, så det er ikke et stort problem her.

Da vi således ikke har væsentlig glæde af GraphQL-APIet, ville et godt alternativ være at hente alle data som filer, og
så udtrække de relevante datapunkter fra disse. Muligheden for at hente filer fra Datafordeleren udfases dog ultimo
2026 som led i moderniseringen til GraphQL-uden-Graph.

### Gem skemaer i `schemas`

Jeg anbefaler at hente GraphQL skemaerne og gemme dem i `schemas` til reference:

- BBR GraphQL Schema: https://datafordeler.dk/GraphQLSchema/BBR.graphql
- VUR GraphQL Schema: https://datafordeler.dk/GraphQLSchema/VUR.graphql
- MAT GraphQL Schema: https://datafordeler.dk/GraphQLSchema/MAT.graphql

### Forespørgsler skal bygges i hånden

Jeg anbefaler at skrive disse i hånden, da "Byg GraphQL Query" funktionen på Datafordeleren
ikke genererer gyldige forespørgsler hvis man spørger på sammensatte typer. Den kan kun bruges
til skitser, skemaet er den eneste reference.

Support-afdelingen hos Datafordeler anbefaler i stedet at bruge trediepartsværktøjer som
[Altair GraphQL](https://altairgraphql.dev/) til at generere gyldige forespørgsler. Fejlen i deres "Byg GraphQL Query"
er en "kendt fejl" (23 marts, 2026), og de har ikke nogen horisont for om og hvornår de retter det.

Et andet nyttigt værktøj er [GraphQL Voyager](https://github.com/APIs-guru/graphql-voyager)
hvor man kan visualisere et GraphQL-skema.

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

#### Kodelisterne er ikke på første normalform

Man skal sætte sig ind i en række kodelister for at bruge systemet, f.eks.:

- VUR DK kodelister: https://confluence.sdfi.dk/pages/viewpage.action?pageId=82346523

Af en eller anden grund er mange af koderne sammensatte, hvor det havde være mere naturligt
at normalisere og adskille ortogonale dimensioner, svarende til første normalform for databaser.
Det øger kompleksiteten af klientapplikationerne og skaber stærkere koblinger end nødvendigt, så
det virker som et overraskende designvalg.

#### Ejendomsvurdering

Dette er selve vurderingen af en vurderingsejendom.

Ejendomme har forskellige anvendelser, vi kigger kun på de mest enkle, `benyttelseKode`:

- `01` Beboelse
- `21` Ejerlejlighed, beboelse

Se https://grunddatamodel.datafordeler.dk/objekttypekatalog/Ejendomsvurdering/Ejendomsvurdering.html#_A22606_62910

#### Vurderingsejendom

Dette er selve den vurderede ejendom.

> vurderingsejendommen består af en eller flere BFE (Bestemt Fast Ejendom) som i vurderingsmæssig henseende skal
> behandles under et

Se https://grunddatamodel.datafordeler.dk/objekttypekatalog/Ejendomsvurdering/Vurderingsejendom.html

Der er flere forskellige nøglefelter, men der dog ikke altid er udfyldt:

- `vurderingsejendomID` *entydig identifikation for en Vurderingsejendom som den forventes at se ud i det fremtidige
  Vurderingssystem ICE. Entydig identifikation for en vurderingsejendom, som kan omfatte en eller flere BFE'er (flere
  ved samvurdering)*
- `VURejendomsid` *VURs entydige identifikation af en ejendom på vurderingstidspunktet*
- (`ESRkommunenummer`, `ESRejendomsnummer`) nøgle til udgåede vurderingsejendomme, der ikke har et BFE-nummer.

Kardinalitet: ca. 2,4 millioner styk pr. april 2026.

#### BFEKrydsreference

Dette er en relation mellem ejendomsvurderinger og bestemte faste ejendomme (BFE) i BBR.

Der er typisk under 100 vurderinger pr. ejendom, middelværdien er omkring 20 vurderinger
per BFE-nummer (april 2026).

Desværre er vurderingsåret ikke med i relationen til filterbrug (`where`),
så man bliver nødt til at hente alle data for alle vurderinger fra API'et,
1000 rækker pr. HTTP-kald.

- `fkEjendomsvurderingID`

Kardinalitet: ca. 50 millioner styk pr. april 2026.

#### Grundvaerdispecifikation

List med specifikationer til grundværdier for ejendomsvurdering.

GraphQL-APIet er også her ganske sjovt,`VUR_GrundvaerdispecifikationFilterInput` lader til udelukkende
at være møntet på klientopslag vedrørende en vurdering ad gangen.

Hvis det er designformålet, ville det være mere oplagt at udstille specifikationerne som en liste direkte på
Ejendomsvurdering snarere end tvinge klienten til ekstra kald for en typisk meget lille datamængde.

Skal man hente alle data skal man således lave et HTTP-kald pr. ejendomsvurdering, eller hente det hele
i sider på maks. 1000 elementer pr. kald.

Der er over 30 millioner datapunkter, og kald tager typisk mellem 0,5 til 2 sekunder, så her skal
man være tålmodig.

### BBR

[Domænemodel: Bygnings- og Boligregisteret, BBR](https://grunddatamodel.datafordeler.dk/objekttypekatalog/Bygninger%20og%20boliger/package-summary.html)

#### Bygning

Der er er mange statuskoder på "Livscyklus" kodelisten (se nedenfor), det lader til
at den relevante til vort brug for `Bygning` er `6 - Opført` og ikke `7 - Gældende` som ellers.

BBR indeholder mange flere bygninger, end folks hjem, de er tildelt anvendelseskoder, `byg021BygningensAnvendelse`.
Se kodelisten her: https://teknik.bbr.dk/kodelister/0/1/0/BygAnvendelse

#### Ejendomsrelation

Denne entitet lader til at benytte Livscyklus statuskoderne.

```
    7 - Gældende
    10 - Historisk
    11 - Fejlregistreret
```

For vor anvendelser er kode 7 den interessante.

Ejendomsrelationen udtaler sig om forskellige ejendomstyper, `ejendomstype`, som alle findes under matrikel subdomænet,
`MAT`:

```
    1 - Matrikuleret Areal
    2 - BPFG
    3 - Ejerlejlighed
```

Se kodelisten https://teknik.bbr.dk/kodelister/0/1/0/Ejendomstype

#### Kodelister

##### Livscyklus

Denne liste lader til at sammenblande livsyklus tilstande for flere forskellige typer data.
Når man se på data for f.eks. `Bygning` er der bygninger med registreringer med status 6 Opført, men ikke med 7
Gældende.
Her ville jeg normalt sige, at der ikke er skat på kodelister, så lad os nu bare definere en for hver anvendelse,  
så klientapplikationerne ikke skal gætte på hvordan semantikken for de samme værdier adskiller sig på tværs af entiteter
eller forlade sig på kommentarer i dokumentationen. Så er det bedre med en eksplicit kobling der kan fungere som
kontrakt.

Se https://teknik.bbr.dk/kodelister/0/1/0/Livscyklus

### MAT

> begrebet "bestemt fast ejendom" stammer oprindeligt fra Tinglysningsloven, men det bemærkes, at i Matriklen
> registreres også ejendomme, hvor der ikke er eller vil blive tinglyst rettigheder på. Bestemt fast ejendom
> underopdeles
> i ejendomstyperne: Samlet fast ejendom, Bygning på fremmed grund (BPFG), Ejerlejlighed - herunder ejerlejlighed i
> BPFG.

Se [Grunddatamodel > Matrikel > BestemtFastEjendom](https://grunddatamodel.datafordeler.dk/objekttypekatalog/)

For enkelthedens skyld nøjes vi således med at læse *Samlet Fast Ejendom* og *Ejerlejlighed*.

#### Ejerlejlighed

Her er `status` en `String` (f.eks. `Gældende`), andre steder i API'et bruges statuskoden `7` for
det samme (7 - Gældende).

#### Samlet fast ejendom

Man kan navigere til denne fra Ejerlejlighed, den har `geometri` som er en multi-polygon.