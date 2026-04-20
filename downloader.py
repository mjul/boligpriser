from __future__ import annotations

import argparse
import asyncio
import collections
import logging
import os
import time
import typing
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from gql import Client, GraphQLRequest, gql
from gql.transport.aiohttp import AIOHTTPTransport


class DefaultExtrasFilter(logging.Filter):
    """
    Default logging filter that sets undefined entity and context attributes to blank.
    Without that the logger would throw if the fields are used in the format string without being set.
    """

    defaults = {"entity": "", "context": ""}

    def filter(self, record):
        for key, val in self.defaults.items():
            if not hasattr(record, key):
                setattr(record, key, val)
        return True


logger = logging.getLogger(__name__)
logger.addFilter(DefaultExtrasFilter())


@dataclass(slots=True)
class DownloaderConfig:
    out_dir: Path = Path("data")
    datafordeler_graphql_url: str = "https://graphql.datafordeler.dk"
    bbr_path: str = "/BBR/v1"
    vur_path: str = "/VUR/v2"
    vurderingsaar: int = 2022  # dette år har flest data, se https://vurdst.dk/udsendelser-af-deklarationer-og-vurderinger
    datafordeler_api_key: str | None = None
    timeout_seconds: int = 120

    @classmethod
    def from_env(cls) -> "DownloaderConfig":
        if not os.getenv("DATAFORDELER_API_KEY"):
            raise DownloaderError("DATAFORDELER_API_KEY is not set")
        return cls(
            out_dir=Path(os.getenv("DATA_DIR", "data")),
            datafordeler_api_key=os.getenv("DATAFORDELER_API_KEY"),
            timeout_seconds=int(os.getenv("HTTP_TIMEOUT_SECONDS", "120")),
        )

    def bbr_url(self):
        """Get the URL for the BBR GraphQL endpoint, including the API key."""
        return f"{self.datafordeler_graphql_url}{self.bbr_path}?apikey={self.datafordeler_api_key}"

    def bbr_bygning_file(self):
        """Get the path to the BBR Bygning Parquet file."""
        return self.out_dir / "bbr_bygning.parquet"

    def bbr_bygning_kommune_file(self, kommunekode: str):
        """Get the path to the BBR Bygning Parquet file."""
        return self.out_dir / f"bbr_bygning-{kommunekode}.parquet"

    def bbr_ejendomsrelation_file(self):
        """Get the path to the BBR Ejendomsrelation Parquet file."""
        return self.out_dir / "bbr_ejendomsrelation.parquet"

    def bbr_ejendomsrelation_kommune_file(self, kommunekode: str):
        """Get the path to the BBR Ejendomsrelation Parquet file."""
        return self.out_dir / f"bbr_ejendomsrelation-{kommunekode}.parquet"

    def vur_url(self):
        """Get the URL for the VUR GraphQL endpoint, including the API key."""
        return f"{self.datafordeler_graphql_url}{self.vur_path}?apikey={self.datafordeler_api_key}"

    def vur_ejendomsvurdering_file(self):
        """Get the path to the VUR Ejendomsvurdering Parquet file."""
        return self.out_dir / "vur_ejendomsvurdering.parquet"

    def vur_vurderingsejendom_file(self):
        """Get the path to the VUR Vurderingsejendom Parquet file."""
        return self.out_dir / "vur_vurderingsejendom.parquet"

    def vur_bfekrydsreference_file(self):
        """Get the path to the VUR BFE Krydsreference Parquet file."""
        return self.out_dir / "vur_bfekrydsreference.parquet"

    def vur_grundvaerdispecifikation_file(self):
        """Get the path to the VUR Grundvaerdispecifikation Parquet file."""
        return self.out_dir / "vur_grundvaerdispecifikation.parquet"


class DownloaderError(RuntimeError):
    pass


async def download_to_parquet(
    url_with_key: str,
    query: GraphQLRequest,
    entity: str,
    log_context: str,
    variable_values: dict[str, typing.Any],
    output_file: Path,
    schema=None,
    transform_table: (collections.abc.Callable[[pa.Table], pa.Table] | None) = None,
    max_entities: int | None = None,
) -> pa.Table:
    """
    Page through all results for a single entity.
    Query must have a $cursor variable for paging.
    Saves data as Parquet file to the output_file.
    Returns {entity: {'nodes': [...]}}
    :param url_with_key:
    :param query:
    :param entity:
    :param log_context: a context field to add to all log messages, use for e.g. part info when downloading in parts
    :param variable_values:
    :param max_entities:
    :param output_file: path to save the Parquet file
    :param schema: optional schema to use for Parquet file
    :param transform_table: optional function to transform the table before saving it to disk
    :return:
    """
    log_adapter = logging.LoggerAdapter(
        logger, {"entity": entity, "context": log_context}
    )

    cursor = None
    has_next_page = True

    transport = AIOHTTPTransport(url=url_with_key, timeout=120)
    client = Client(transport=transport)

    page_tables = []
    n_read = 0
    MAX_RETRIES: int = 42
    retries_left: int = MAX_RETRIES
    done = False

    # We create a whole new session when we retry fetching a page
    while (not done) and (retries_left > 0):
        try:
            async with client as session:
                while has_next_page:
                    log_adapter.info(f"Downloading page with cursor: {cursor}")
                    vvals = variable_values.copy()
                    vvals.update({"cursor": cursor})

                    start_time = time.perf_counter()
                    result = await session.execute(query, variable_values=vvals)
                    duration = time.perf_counter() - start_time
                    log_adapter.info(f"Page downloaded in {duration:.2f}s")

                    entity_page = result[entity]
                    table = pa.Table.from_pylist(entity_page["nodes"], schema=schema)
                    page_tables.append(table)

                    n_read += table.num_rows

                    duration = time.perf_counter() - start_time
                    log_adapter.info(f"Page processed in {duration:.2f}s.")
                    log_adapter.info(f"Processed {n_read} rows in total.")

                    if max_entities is not None and max_entities <= n_read:
                        # stop if we have enough entities
                        done = True
                        break

                    has_next_page = entity_page["pageInfo"]["hasNextPage"]
                    cursor = entity_page["pageInfo"]["endCursor"]

                    if not has_next_page:
                        done = True

                    # Reset on success
                    retries_left = MAX_RETRIES

        except Exception as e:
            log_adapter.warning(f"Error downloading page with cursor {cursor}: {e}")
            retries_left -= 1
            await asyncio.sleep(0.5)
            log_adapter.warning(f"Retrying download (Retries left: {retries_left})...")

    # Promote options: so if one table has column type string and another type null (for sparse data)
    # it will promote the null type to a (nullable) string type
    table = pa.concat_tables(page_tables, promote_options="default")

    if transform_table:
        table = transform_table(table)

    log_adapter.info(f"Writing {table.num_rows} rows to {output_file}...")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output_file)
    log_adapter.info(f"Saved data to {output_file.name}")

    return table


def combine_parquet_files(input_files: list[Path], output_file: Path) -> None:
    """Combine multiple Parquet files into one. Input files must have the same schema."""
    assert input_files is not None
    assert output_file is not None
    assert len(input_files) > 0
    assert all(input_file.exists() for input_file in input_files)
    logger.info(f"Combining {len(input_files)} Parquet files into {output_file}...")
    schema = pq.ParquetFile(input_files[0]).schema.to_arrow_schema()
    with pq.ParquetWriter(output_file, schema) as writer:
        for file in input_files:
            logger.info(f"Adding {file} to {output_file}...")
            table = pq.read_table(file)
            writer.write_table(table)


#
# KOMMUNEKODER
#
# Fanø: 0563
# Læsø: 0825
#
# https://danmarksadresser.dk/adressedata/kodelister/kommunekodeliste/

# Vi bruger nogle af de små kommuner til at eksperimentere med
KOMMUNEKODER: dict[str, str] = {
    "0155": "Dragør",
    "0482": "Langeland",
    "0563": "Fanø",
    "0825": "Læsø",
}  # TODO: complete
KOMMUNEKODE_LÆSØ = "0825"


async def download_for_alle_kommuner(
    filenamer: typing.Callable[[str], Path],
    downloader: typing.Callable[[str, Path, str], typing.Awaitable[None]],
    output_file: Path,
) -> None:
    """Run the downloader for all kommuner, writing to the shard files specified by the filenamer function
    then combining them into one output file.
    The filenamer and downloader functions take a kommunekode as input."""
    kommune_files: typing.List[Path] = []
    for i, (kommunekode, kommunenavn) in enumerate(sorted(KOMMUNEKODER.items())):
        logger.info(
            f"Downloading data for {kommunenavn} ({kommunekode})...",
            extra={"entity": "", "context": ""},
        )
        log_context = (
            f"{i + 1}/{len(KOMMUNEKODER)} {kommunekode} {KOMMUNEKODER[kommunekode]}"
        )
        kommune_output_file = filenamer(kommunekode)
        kommune_files.append(kommune_output_file)
        await downloader(kommunekode, kommune_output_file, log_context)

    # Take all the kommune files and combine them into one
    # We could also use a Parquet Dataset, but let's keep it simple, it is very little data
    if kommune_files:
        combine_parquet_files(kommune_files, output_file)


async def download_bbr_bygning(config: DownloaderConfig):
    max_entities = None  # Hent alle
    await download_for_alle_kommuner(
        lambda kommunekode: config.bbr_bygning_kommune_file(kommunekode),
        lambda kommunekode, output_file, log_context: download_bbr_bygning_kommune(
            config, kommunekode, output_file, log_context, max_entities=max_entities
        ),
        config.bbr_bygning_file(),
    )


async def download_bbr_bygning_kommune(
    config: DownloaderConfig,
    kommunekode: str,
    output_file: Path,
    log_context: str,
    max_entities: int | None,
):
    """Hent alle bygninger i en kommune."""
    if kommunekode not in KOMMUNEKODER:
        raise DownloaderError(f"Kommunekode {kommunekode} is not supported")

    url_with_key = config.bbr_url()

    query = gql(
        """
        query GetBBRBygninger($cursor: String, $kommunekode: String!) {
          BBR_Bygning(
            virkningstid: "2026-01-01T00:00:00+01:00"
            first: 1000
            after: $cursor
            where: {
              kommunekode: {eq: $kommunekode}
              status: {eq: "6"} # 6 er "Opført"
              byg021BygningensAnvendelse: {in: ["120", "140"]} # begræns til villaer og lejligheder
            }
          ) {
            pageInfo {
              endCursor
              hasNextPage
            }
            nodes {
                id_lokalId
                kommunekode
                status # kode for bygværkselementets status i den pågældende version, dvs. elementets tilstand i den samlede livscyklus
                byg007Bygningsnummer # angiver bygningens nummer indenfor ejendommen
                byg021BygningensAnvendelse # angiver bygningens hovedanvendelse, se kodeliste https://teknik.bbr.dk/kodelister/0/1/0/BygAnvendelse
                byg026Opfoerelsesaar
                byg027OmTilbygningsaar
                byg070Fredning # angiver om bygningen er fredet
                byg071BevaringsvaerdighedReference # linker til Kulturstyrelsens registrering i FBB (Fredede og Bevaringsværdige Bygninger)
                grund
                byg404Koordinat { type crs dimension wkt } # angiver bygningens geografiske repræsentation i form af et punkt
                byg406Koordinatsystem
                virkningFra # tidspunktet hvor virkningen af den pågældende version af bygværkselementet er startet
                virkningTil # tidspunktet hvor virkningen af den pågældende version af bygværkselementet ophører
            }
          }
        }    
        """
    )
    logger.info(
        f"Downloading BBR bygning data for {kommunekode} {KOMMUNEKODER[kommunekode]}...",
        extra={"entity": "", "context": ""},
    )
    schema = pa.schema(
        [
            pa.field("id_lokalId", pa.string(), nullable=False),
            pa.field("kommunekode", pa.string()),
            pa.field("status", pa.string()),
            pa.field("byg007Bygningsnummer", pa.int64(), nullable=True),
            pa.field("byg021BygningensAnvendelse", pa.string()),
            pa.field("byg026Opfoerelsesaar", pa.int32(), nullable=True),
            pa.field("byg027OmTilbygningsaar", pa.int32(), nullable=True),
            pa.field("byg070Fredning", pa.string(), nullable=True),
            pa.field("byg071BevaringsvaerdighedReference", pa.string(), nullable=True),
            pa.field("grund", pa.string()),
            pa.field(
                "byg404Koordinat",
                pa.struct(
                    [
                        pa.field("type", pa.string()),
                        pa.field("crs", pa.int32(), nullable=False),
                        pa.field("dimension", pa.string()),
                        pa.field("wkt", pa.string()),
                    ]
                ),
            ),
            pa.field("byg406Koordinatsystem", pa.string()),
            pa.field(
                "virkningFra", pa.string()
            ),  # TODO: convert to timestamp after loading
            pa.field(
                "virkningTil", pa.string()
            ),  # TODO: convert to timestamp after loading
        ]
    )
    entity = "BBR_Bygning"

    def parse_timestamps(t: pa.Table) -> pa.Table:
        vf_col = pc.cast(t["virkningFra"], pa.timestamp("us", tz="UTC"))
        vt_col = pc.cast(t["virkningTil"], pa.timestamp("us", tz="UTC"))
        t = t.set_column(t.schema.get_field_index("virkningFra"), "virkningFra", vf_col)
        t = t.set_column(t.schema.get_field_index("virkningTil"), "virkningTil", vt_col)
        return t

    _result = await download_to_parquet(
        url_with_key,
        query,
        entity,
        log_context,
        {"kommunekode": kommunekode},
        output_file,
        schema=schema,
        transform_table=parse_timestamps,
        max_entities=max_entities,
    )


async def download_bbr_ejendomsrelation(config: DownloaderConfig) -> None:
    max_entities = None  # Hent alle
    await download_for_alle_kommuner(
        lambda kommunekode: config.bbr_ejendomsrelation_kommune_file(kommunekode),
        lambda kommunekode, output_file, log_context: (
            download_bbr_ejendomsrelation_kommune(
                config, kommunekode, output_file, log_context, max_entities=max_entities
            )
        ),
        config.bbr_ejendomsrelation_file(),
    )


async def download_bbr_ejendomsrelation_kommune(
    config: DownloaderConfig,
    kommunekode: str,
    output_file: Path,
    log_context: str,
    max_entities: int | None,
):
    """Hent alle bygninger i en kommune."""
    if kommunekode not in KOMMUNEKODER:
        raise DownloaderError(f"Kommunekode {kommunekode} is not supported")

    url_with_key = config.bbr_url()

    query = gql(
        """
        query GetBBREjendomsrelation($cursor: String, $kommunekode: String!) {
          BBR_Ejendomsrelation(
            virkningstid: "2026-01-01T00:00:00+01:00"
            first: 1000
            after: $cursor
            where: {
              kommunekode: {eq: $kommunekode}
              status: {
                eq: "7" # status 7: Gældende
              }
            }
          ) {
            pageInfo {
              endCursor
              hasNextPage
            }
            nodes {
                id_lokalId
                kommunekode
                status # kode for bygværkselementets status i den pågældende version, dvs. elementets tilstand i den samlede livscyklus 
                bfeNummer # Long, angiver den fælles ejendomsidentifikation for den bestemte faste ejendom som den tilhørende BBR-entitet udgør eller indgår 
                ejendomsnummer # String
                ejendomstype # String
                ejerlejlighed # String
                ejerlejlighedsnummer # Long
                vurderingsejendomsnummer # Long
                virkningFra # tidspunktet hvor virkningen af den pågældende version af bygværkselementet er startet
                virkningTil # tidspunktet hvor virkningen af den pågældende version af bygværkselementet ophører
            }
          }
        }    
        """
    )
    entity = "BBR_Ejendomsrelation"
    logger.info(
        "Downloading BBR ejendomsrelation data...",
        extra={"entity": entity, "context": log_context},
    )

    def parse_timestamps(t: pa.Table) -> pa.Table:
        vf_col = pc.cast(t["virkningFra"], pa.timestamp("us", tz="UTC"))
        vt_col = pc.cast(t["virkningTil"], pa.timestamp("us", tz="UTC"))
        t = t.set_column(t.schema.get_field_index("virkningFra"), "virkningFra", vf_col)
        t = t.set_column(t.schema.get_field_index("virkningTil"), "virkningTil", vt_col)
        return t

    _result = await download_to_parquet(
        url_with_key,
        query,
        entity,
        log_context,
        {"kommunekode": kommunekode},
        output_file,
        schema=None,
        transform_table=parse_timestamps,
        max_entities=max_entities,
    )


async def download_vur_ejendomsvurdering(config: DownloaderConfig) -> None:
    url_with_key = config.vur_url()
    output_file = config.vur_ejendomsvurdering_file()

    # Paged query for BBR Bygninger
    query = gql(
        """
        query GetVUR_Ejendomsvurdering($cursor: String, $vurderingsaar: Long!) {
          VUR_Ejendomsvurdering(
            first: 1000
            after: $cursor
            where: {
              ajourfoeringDato: {lt: "2026-01-01T00:00:00+01:00"}
              aar: {eq: $vurderingsaar}
            }
          ) {
            pageInfo {
              endCursor
              hasNextPage
            }
            nodes {
                id
                datafordelerRowId
                datafordelerRowVersion
                aar
                ejendomvaerdiBeloeb
                grundvaerdiBeloeb
                juridiskKategoriKode # Kode der angiver den juridiske kategori, som ejendommen er tildelt ved denne ejendomsvurdering.
                juridiskKategoriTekst # Tekst, der beskriver den juridiske kategori, som ejendommen er tildelt ved denne ejendomsvurdering
                juridiskUnderkategoriKode
                juridiskUnderkategoriTekst
                vurderetAreal # Vurderet grundareal. Ejendommens samlede vurderede areal i m2 (incl. Vejareal).
                ajourfoeringDato # Timestamp for hvornår en vurdering, en eventuel vurderingsændring, årsregulering eller §4/4A vurdering er  opdateret enten maskinelt ved en batch-kørsel eller i forbindelse med sagsbehandling.
                aendringDato # Dato for seneste gældende vurdering.
                benyttelseKode
                antalMedvurderedeLejligheder # Antal medvurderede lejligheder i den vurderede ejendom
                vurderingskredsKode
                VURMark # Angiver kilde-system og type for vurderingen -- nødvendig for at afgøre om det er den gældende vurdering
                fkModerejendomID
                fkVurderetUnderID
                fkVurderingsejendomID
            }
          }
        }    
        """
    )

    entity = "VUR_Ejendomsvurdering"
    log_context = f"{config.vurderingsaar}"

    def parse_timestamps_and_encode_categorical_labels(t: pa.Table) -> pa.Table:
        aj_col = pc.cast(
            t["ajourfoeringDato"], pa.timestamp("us", tz="UTC")
        )  # Example: `2025-10-02T12:30:01.000000Z`
        # we do not convert aendringDato since Arrow does not have a local-date like data type (date32 would be closest)
        t = t.set_column(
            t.schema.get_field_index("ajourfoeringDato"), "ajourfoeringDato", aj_col
        )
        # Simple conversion (not using '...kode' as key)
        jk_col = t.column("juridiskKategoriTekst").combine_chunks().dictionary_encode()
        ju_col = t.column("juridiskUnderkategoriTekst").combine_chunks().dictionary_encode()
        t = t.set_column(
            t.schema.get_field_index("juridiskKategoriTekst"),
            "juridiskKategoriTekst",
            jk_col,
        )
        t = t.set_column(
            t.schema.get_field_index("juridiskUnderkategoriTekst"),
            "juridiskUnderkategoriTekst",
            ju_col,
        )
        return t

    result = await download_to_parquet(
        url_with_key,
        query,
        entity,
        log_context,
        {"vurderingsaar": config.vurderingsaar},
        output_file,
        transform_table=parse_timestamps_and_encode_categorical_labels,
        max_entities=None,  # download alle for vurderingsåret
    )


async def download_vur_vurderingsejendom(config: DownloaderConfig) -> None:
    url_with_key = config.vur_url()
    output_file = config.vur_vurderingsejendom_file()

    query = gql(
        """
        query GetVUR_Vurderingsejendom($cursor: String) {
          VUR_Vurderingsejendom(
            first: 1000
            after: $cursor
          ) {
            pageInfo {
              endCursor
              hasNextPage
            }
            nodes {
                vurderingsejendomID
                datafordelerRowId
                datafordelerRowVersion
                datafordelerOpdateringstid
                ESRejendomsnummer
                ESRkommunenummer
                VURejendomsid
            }
          }
        }    
        """
    )
    max_entities = None  # Download all

    entity = "VUR_Vurderingsejendom"
    log_context = ""
    _result = await download_to_parquet(
        url_with_key,
        query,
        entity,
        log_context,
        {},
        output_file,
        max_entities=max_entities,
    )


async def download_vur_bfekrydsreference(config: DownloaderConfig) -> None:
    url_with_key = config.vur_url()
    output_file = config.vur_bfekrydsreference_file()

    query = gql(
        """
        query GetVUR_BFEKrydsreference($cursor: String) {
          VUR_BFEKrydsreference(
            first: 1000
            after: $cursor
          ) {
            pageInfo {
              endCursor
              hasNextPage
            }
            nodes {
                BFEKrydsreferenceID
                BFEnummer
                datafordelerRowId
                datafordelerRowVersion
                datafordelerOpdateringstid
                fkEjendomsvurderingID
            }
          }
        }    
        """
    )
    max_entities = None  # Hent alle

    entity = "VUR_BFEKrydsreference"
    log_context = ""
    _result = await download_to_parquet(
        url_with_key,
        query,
        entity,
        log_context,
        {},
        output_file,
        max_entities=max_entities,
    )


async def download_vur_grundvaerdispecifikation(config: DownloaderConfig) -> None:
    url_with_key = config.vur_url()
    output_file = config.vur_grundvaerdispecifikation_file()

    query = gql(
        """
        query GetVUR_Grundvaerdispecifikation($cursor: String) {
          VUR_Grundvaerdispecifikation(
            first: 1000
            after: $cursor
          ) {
            pageInfo {
              endCursor
              hasNextPage
            }
            nodes {
                GrundvaerdispecifikationID
                loebenummer # Fortløbende nummer pr specifikation.
                datafordelerRowId
                datafordelerRowVersion
                datafordelerOpdateringstid
                fkEjendomsvurderingID
                areal # Angivelse af arealet i m2 pr. specifikation.
                beloeb # Udregnet grundværdi (i hele kr.) for en given grundværdispecifikation.
                enhedBeloeb # Enhedsbeløb angiver prisen pr. enhed i en grundværdispecifikation.
                prisKode # Priskoden angiver arten af en enhedspris i en grundværdispecifikation.
                tekst # Forklarende tekst i tilknytning til en grundværdispecifikation.
            }
          }
        }    
        """
    )

    entity = "VUR_Grundvaerdispecifikation"
    log_context = ""
    _result = await download_to_parquet(
        url_with_key,
        query,
        entity,
        log_context,
        {},
        output_file,
        max_entities=None,  # ingen grænse, hent alle
    )


# Bitemporalitet (VUR)
# https://confluence.sdfi.dk/pages/viewpage.action?pageId=16056524
# NB: *Der er ikke bitemporalitet i VUR, og VUR følger ikke modelreglerne, da det er udviklet før disse blev vedtaget.*


def cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect Danish property-related public data to GeoParquet/Parquet"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    bbr_sub = sub.add_parser("bbr", help="Download BBR data to Parquet/GeoParquet")
    _ = bbr_sub.add_argument(
        "tabeller", nargs="*", choices=["bygning", "ejendomsrelation"]
    )
    vur_sub = sub.add_parser("vur", help="Download VUR data to Parquet/GeoParquet")
    _ = vur_sub.add_argument(
        "tabeller",
        nargs="*",
        choices=[
            "ejendomsvurdering",
            "vurderingsejendom",
            "bfekrydsreference",
            "grundvaerdispecifikation",
        ],
    )
    return parser


async def download(config, args):
    if args.command == "bbr":
        if "bygning" in args.tabeller:
            await download_bbr_bygning(config)
        if "ejendomsrelation" in args.tabeller:
            await download_bbr_ejendomsrelation(config)
    elif args.command == "vur":
        if "ejendomsvurdering" in args.tabeller:
            await download_vur_ejendomsvurdering(config)
        if "vurderingsejendom" in args.tabeller:
            await download_vur_vurderingsejendom(config)
        if "bfekrydsreference" in args.tabeller:
            await download_vur_bfekrydsreference(config)
        if "grundvaerdispecifikation" in args.tabeller:
            await download_vur_grundvaerdispecifikation(config)
    else:
        raise DownloaderError(f"Unknown command: {args.command}")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(entity)s] [%(context)s] %(message)s"
    )

    args = cli_parser().parse_args()
    config = DownloaderConfig.from_env()
    asyncio.run(download(config, args))


if __name__ == "__main__":
    main()
