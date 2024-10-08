# This tool generates Python data types from the ED-318 JSON Schema files.
# The ED-318 approach is sufficiently non-standard that it needs full custom processing.

import argparse
import glob
import json
import os
from typing import Dict

import yaml

import data_types
import flattening
import operations
import rendering


def _parse_args():
    parser = argparse.ArgumentParser(description='Autogenerate Python data types from ED-318 JSON Schema')

    # Input/output specifications
    parser.add_argument('--reporoot', dest='reporoot', type=str, default=None,
                        help='Root of repository.')

    return parser.parse_args()


def _replace_refs(obj, ref_changes: Dict[str, str]) -> None:
    if isinstance(obj, dict):
        if "$ref" in obj:
            for old_ref, new_ref in ref_changes.items():
                if obj["$ref"] == old_ref:
                    obj["$ref"] = new_ref
        else:
            for v in obj.values():
                _replace_refs(v, ref_changes)

    elif isinstance(obj, list) and not isinstance(obj, str):
        for v in obj:
            _replace_refs(v, ref_changes)


def main():
    args = _parse_args()

    # Load raw JSON Schema files
    schemas = {}
    for schemafile in glob.glob(os.path.join(args.reporoot, "interfaces/eurocae/ed318/schema/*.json")):
        filepart = os.path.split(schemafile)[-1]
        with open(schemafile, mode='r') as f:
            schemas[filepart] = json.load(f)

    # Replace external refs with flattened refs
    object_names = {
        "Schema_GeoZones.json": "FeatureCollection",
        "Schema_GeoZoneCollectionMetadata.json": "DatasetMetadata",
        "Schema_GeoJSONGeometries.json": "Geometry",
        "Schema_GeoZoneProperties.json": "UASZone",
        "Schema_GeoZoneAuthority.json": "Authority",
        "Schema_GeoZoneTimePeriod.json": "TimePeriod",
    }
    _replace_refs(schemas, {"./" + k: "#/components/schemas/" + v for k, v in object_names.items()})

    # Collect objects for flattened spec
    objects = {v: schemas[k] for k, v in object_names.items()}

    # Extract data types from files with `definitions`
    data_type_refs = {}
    for schema_name in schemas:
        if "definitions" not in schemas[schema_name]:
            continue
        for k, v in schemas[schema_name]["definitions"].items():
            object_name = k[0].upper() + k[1:]
            data_type_refs[f"./{schema_name}#/definitions/" + k] = "#/components/schemas/" + object_name
            data_type_refs[f"#/definitions/" + k] = "#/components/schemas/" + object_name
            objects[object_name] = v
        del schemas[schema_name]["definitions"]
    _replace_refs(objects, data_type_refs)

    # Extract Feature definition from Schema_GeoZones.json
    objects["Feature"] = objects["FeatureCollection"]["properties"]["features"].pop("items")
    objects["FeatureCollection"]["properties"]["features"]["items"] = {"$ref": "#/components/schemas/Feature"}

    # Extract specific geometry types from NormalGeometry
    normal_geometry_oneof = []
    for schema in objects["NormalGeometry"]["allOf"][0]["oneOf"]:
        if schema["type"] == "null":
            # This option is not actually possible because NormalGeometry must also satisfy all of LayeredGeoJSON which specifies type=object
            continue
        object_name = schema["properties"]["type"]["enum"][0]
        for k, v in schemas["Schema_LayeredGeoJSON.json"]["properties"].items():
            schema["properties"][k] = v
        normal_geometry_oneof.append({"$ref": "#/components/schemas/" + object_name})
        objects[object_name] = schema
    objects["NormalGeometry"] = {"oneOf": normal_geometry_oneof}
    _replace_refs(objects, data_type_refs)

    # Manually merge GeometryCollection's allOf
    objects["GeometryCollection"] = objects["GeometryCollection"]["allOf"][0]
    for k, v in schemas["Schema_LayeredGeoJSON.json"]["properties"].items():
        objects["GeometryCollection"]["properties"][k] = v

    # Convert `title`s to `description`s
    for v in objects.values():
        if "title" in v:
            v["description"] = v.pop("title")

    # Create flattened spec
    spec = {"components": {"schemas": objects}}

    # Parse data types
    types = data_types.parse(spec)

    # Render Python code
    with open(os.path.join(args.reporoot, "src/uas_standards/eurocae/ed318.py"), 'w') as f:
        f.write(f'"""Data types for ED-318"""\n\n')
        f.write('\n'.join(rendering.header(types)))
        f.write('\n\n\n')
        f.write('\n'.join(rendering.data_types(types, '')))
        f.write('\n')

if __name__ == '__main__':
    main()
