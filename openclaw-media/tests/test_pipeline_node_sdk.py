import pytest

from openclaw_media.node_sdk import OutputBoundaryError, validate_outputs


DECLARED = [
    {
        "name": "video",
        "mime_types": ["video/mp4"],
        "max_bytes": 1024,
        "upload": "descriptor_only",
    }
]


def test_valid_descriptor_stays_local():
    validate_outputs(
        DECLARED,
        {
            "video": {
                "local_path": "/tmp/output.mp4",
                "mime_type": "video/mp4",
                "size_bytes": 100,
                "cloud_bytes": 0,
            }
        },
    )


@pytest.mark.parametrize(
    "produced, message",
    [
        ({"other": {}}, "undeclared outputs"),
        (
            {
                "video": {
                    "local_path": "/tmp/x",
                    "mime_type": "image/png",
                    "size_bytes": 1,
                    "cloud_bytes": 0,
                }
            },
            "MIME type",
        ),
        (
            {
                "video": {
                    "local_path": "/tmp/x",
                    "mime_type": "video/mp4",
                    "size_bytes": 2048,
                    "cloud_bytes": 0,
                }
            },
            "max_bytes",
        ),
        (
            {
                "video": {
                    "local_path": "/tmp/x",
                    "mime_type": "video/mp4",
                    "size_bytes": 1,
                    "cloud_bytes": 1,
                }
            },
            "uploaded bytes",
        ),
    ],
)
def test_output_boundary_violations_refuse_execution(produced, message):
    with pytest.raises(OutputBoundaryError, match=message):
        validate_outputs(DECLARED, produced)


def test_forbidden_output_refuses_execution():
    forbidden = [{**DECLARED[0], "upload": "forbidden"}]
    with pytest.raises(OutputBoundaryError, match="forbidden"):
        validate_outputs(
            forbidden,
            {
                "video": {
                    "local_path": "/tmp/x",
                    "mime_type": "video/mp4",
                    "size_bytes": 1,
                    "cloud_bytes": 0,
                }
            },
        )
