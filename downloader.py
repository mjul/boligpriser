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
import pyarrow.parquet as pq
from gql import Client, GraphQLRequest, gql
from gql.transport.aiohttp import AIOHTTPTransport

logger = logging.getLogger(__name__)

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

    def vur_url(self):
        """Get the URL for the VUR GraphQL endpoint, including the API key."""
        return f"{self.datafordeler_graphql_url}{self.vur_path}?apikey={self.datafordeler_api_key}"

    def vur_ejendomsvurdering_file(self):
        """Get the path to the VUR Ejendomsvurdering Parquet file."""
        return self.out_dir / "vur_ejendomsvurdering.parquet"


class DownloaderError(RuntimeError):
    pass


#
# KOMMUNEKODER
#
# Fanø: 0563
# Læsø: 0825
#


async def download_bbr(config: DownloaderConfig) -> None:
    url_with_key = config.bbr_url()

    # Paged query for BBR Bygninger
    query = gql(
        """
        query GetBBRBygninger($cursor: String) {
          BBR_Bygning(
            virkningstid: "2026-01-01T00:00:00+01:00"
            first: 1000
            after: $cursor
            where: {
              kommunekode: {eq: "0825"}
              status: {eq: "6"}
            }
          ) {
            pageInfo {
              endCursor
              hasNextPage
            }
            nodes {
                id_lokalId
                id_namespace
                kommunekode
                status
                byg026Opfoerelsesaar
                byg027OmTilbygningsaar
                byg021BygningensAnvendelse
                byg070Fredning
                byg071BevaringsvaerdighedReference
                grund
                byg404Koordinat { type crs dimension wkt }
                byg406Koordinatsystem
            }
          }
        }    
        """
    )

    max_entities = 1_000  # TODO fix this
    output_file = config.bbr_bygning_file()
    entity = "BBR_Bygning"
    _result = await download_to_parquet(url_with_key, query, entity, {}, max_entities, output_file)


async def download_to_parquet(
    url_with_key: str,
    query: GraphQLRequest,
    entity: str,
    variable_values: dict[str, typing.Any],
    max_entities: int,
    output_file: Path,
) -> pa.Table:
    """
    Page through all results for a single entity.
    Query must have a $cursor variable for paging.
    Saves data as Parquet file to the output_file.
    Returns {entity: {'nodes': [...]}}
    :param url_with_key:
    :param query:
    :param entity:
    :param variable_values:
    :param max_entities:
    :param output_file: path to save the Parquet file
    :return:
    """
    log_adapter = logging.LoggerAdapter(logger, {"entity": entity})

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
            table = pa.Table.from_pylist(entity_page["nodes"])
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

    table = pa.concat_tables(page_tables)
    log_adapter.info(f"Writing {table.num_rows} rows to {output_file}...")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output_file)
    log_adapter.info(f"Saved data to {output_file.name}")

    return table


async def download_vur(config: DownloaderConfig) -> None:
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
    max_entities = 2_000  # TODO

    entity = "VUR_Ejendomsvurdering"
    result = await download_to_parquet(
        url_with_key,
        query,
        entity,
        {"vurderingsaar": config.vurderingsaar},
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
    p_gql = sub.add_parser("bbr", help="Download BBR data to Parquet/GeoParquet")
    p_gql = sub.add_parser("vur", help="Download VUR data to Parquet/GeoParquet")
    return parser


async def download(config, args):
    if args.command == "bbr":
        await download_bbr(config)
    elif args.command == "vur":
        await download_vur(config)
    else:
        raise DownloaderError(f"Unknown command: {args.command}")



def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(entity)s] %(message)s")
    args = cli_parser().parse_args()
    config = DownloaderConfig.from_env()
    asyncio.run(download(config, args))


if __name__ == "__main__":
    main()
