from __future__ import annotations

import argparse
import asyncio
import collections
import os
import typing
from dataclasses import dataclass
from pathlib import Path

from gql import Client, GraphQLRequest, gql
from gql.transport.aiohttp import AIOHTTPTransport


@dataclass(slots=True)
class DownloaderConfig:
    out_dir: Path = Path("data")
    datafordeler_graphql_url: str = "https://graphql.datafordeler.dk"
    bbr_path: str = "/BBR/v1"
    vur_path: str = "/VUR/v2"
    vurderingsaar: int = 2022
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

    def vur_url(self):
        """Get the URL for the VUR GraphQL endpoint, including the API key."""
        return f"{self.datafordeler_graphql_url}{self.vur_path}?apikey={self.datafordeler_api_key}"


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

    max_entities = 2000  # TODO fix this
    result = await get_all_pages_with_cursor(
        url_with_key, query, "BBR_Bygning", {}, max_entities
    )

    print(
        len(result["BBR_Bygning"]["nodes"]),
        collections.Counter(b["id_lokalId"] for b in result["BBR_Bygning"]["nodes"]),
    )

    for n in result["BBR_Bygning"]["nodes"][:10]:
        print(n)


# Page through all results for a single entity.
# Query must have a $cursor variable for paging.
# Returns {entity: {'nodes': [...]}}
async def get_all_pages_with_cursor(
    url_with_key: str,
    query: GraphQLRequest,
    entity: str,
    variable_values: dict[str, typing.Any],
    max_entities: int,
):
    entity_nodes = []
    cursor = None
    has_next_page = True

    transport = AIOHTTPTransport(url=url_with_key, timeout=120)
    client = Client(transport=transport)

    async with client as session:
        while has_next_page:

            print(f"Fetching page with cursor: {cursor}")
            vvals = variable_values.copy()
            vvals.update({"cursor": cursor})

            result = await session.execute(query, variable_values=vvals)

            entity_page = result[entity]
            entity_nodes.extend(entity_page["nodes"])

            if max_entities <= len(entity_nodes):
                # stop if we have enough entities
                break

            has_next_page = entity_page["pageInfo"]["hasNextPage"]
            cursor = entity_page["pageInfo"]["endCursor"]

    return {entity: {"nodes": entity_nodes}}


async def download_vur(config: DownloaderConfig) -> None:
    url_with_key = config.vur_url()

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
                ajourfoeringDato
                aendringDato
                benyttelseKode
                antalMedvurderedeLejligheder # Antal medvurderede lejligheder i den vurderede ejendom
                vurderingskredsKode
                fkVurderingsejendomID
            }
          }
        }    
        """
    )
    max_entities = 10000  # TODO

    result = await get_all_pages_with_cursor(
        url_with_key,
        query,
        "VUR_Ejendomsvurdering",
        {"vurderingsaar": config.vurderingsaar},
        max_entities,
    )

    print(len(result["VUR_Ejendomsvurdering"]["nodes"]))
    for x in result["VUR_Ejendomsvurdering"]["nodes"][:10]:
        print(x)


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
    args = cli_parser().parse_args()
    config = DownloaderConfig.from_env()
    asyncio.run(download(config, args))


if __name__ == "__main__":
    main()
