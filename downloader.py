from __future__ import annotations

import argparse
import asyncio
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
    timeout_seconds: int = 120.0

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


class DownloaderError(RuntimeError):
    pass


async def download_to_parquet(
    url_with_key: str,
    query: GraphQLRequest,
    entity: str,
    log_context: str,
    variable_values: dict[str, typing.Any],
    max_entities: int,
    output_file: Path,
    schema=None,
    transform_table: typing.Callable[pa.Table, pa.Table] | None = None,
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

            if max_entities <= n_read:
                # stop if we have enough entities
                break

            has_next_page = entity_page["pageInfo"]["hasNextPage"]
            cursor = entity_page["pageInfo"]["endCursor"]

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


#
# KOMMUNEKODER
#
# Fanø: 0563
# Læsø: 0825
#
# https://danmarksadresser.dk/adressedata/kodelister/kommunekodeliste/

KOMMUNEKODER: dict[str, str] = {"0563": "Fanø", "0825": "Læsø"}  # TODO: complete
KOMMUNEKODE_LÆSØ = "0825"


async def download_bbr_bygning(config: DownloaderConfig):
    kommunekode = KOMMUNEKODE_LÆSØ
    max_entities = 1_000_000_000  # TODO fix this

    # TODO: alle kommunekoder
    log_context = f"1/{len(KOMMUNEKODER)} {kommunekode} {KOMMUNEKODER[kommunekode]}"
    kommune_output_file = config.bbr_bygning_kommune_file(kommunekode)
    await download_bbr_bygning_kommune(
        config, kommunekode, kommune_output_file, log_context, max_entities
    )

    # TODO: aggregate into one file
    output_file = config.bbr_bygning_file()


async def download_bbr_bygning_kommune(
    config: DownloaderConfig,
    kommunekode: str,
    output_file: Path,
    log_context: str,
    max_entities: int,
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
              status: {eq: "6"}
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
                byg021BygningensAnvendelse # angiver bygningens hovedanvendelse
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
        max_entities,
        output_file,
        schema=schema,
        transform_table=parse_timestamps,
    )


async def download_bbr_ejendomsrelation(config: DownloaderConfig) -> None:
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
    logger.info(
        "Downloading BBR ejendomsrelation data...",
        extra={"entity": "", "context": ""},
    )
    entity = "BBR_Ejendomsrelation"
    log_context = "*"

    def parse_timestamps(t: pa.Table) -> pa.Table:
        print(t.schema)
        vf_col = pc.cast(t["virkningFra"], pa.timestamp("us", tz="UTC"))
        vt_col = pc.cast(t["virkningTil"], pa.timestamp("us", tz="UTC"))
        t = t.set_column(t.schema.get_field_index("virkningFra"), "virkningFra", vf_col)
        t = t.set_column(t.schema.get_field_index("virkningTil"), "virkningTil", vt_col)
        return t

    kommunekode = KOMMUNEKODE_LÆSØ  # TODO
    output_file = config.bbr_ejendomsrelation_kommune_file(kommunekode)
    max_entities = 1_000_000  # TODO

    _result = await download_to_parquet(
        url_with_key,
        query,
        entity,
        log_context,
        {"kommunekode": kommunekode},
        max_entities,
        output_file,
        schema=None,
        transform_table=parse_timestamps,
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
                fkVurderingsejendomID
            }
          }
        }    
        """
    )
    max_entities = 5_000_000  # TODO

    entity = "VUR_Ejendomsvurdering"
    log_context = f"{config.vurderingsaar}"
    result = await download_to_parquet(
        url_with_key,
        query,
        entity,
        log_context,
        {"vurderingsaar": config.vurderingsaar},
        max_entities,
        output_file,
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
    max_entities = 10_000_000  # TODO

    entity = "VUR_Vurderingsejendom"
    log_context = ""
    _result = await download_to_parquet(
        url_with_key,
        query,
        entity,
        log_context,
        {},
        max_entities,
        output_file,
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
    max_entities = 1_000_000_000  # TODO

    entity = "VUR_BFEKrydsreference"
    log_context = ""
    _result = await download_to_parquet(
        url_with_key,
        query,
        entity,
        log_context,
        {},
        max_entities,
        output_file,
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
        choices=["ejendomsvurdering", "vurderingsejendom", "bfekrydsreference"],
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
