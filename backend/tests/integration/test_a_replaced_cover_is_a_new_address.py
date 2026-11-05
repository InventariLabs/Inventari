"""Replacing an item's photo changes the address the screens load.

The cover used to be saved as ``cover.<ext>`` every time, so the address of
the new picture was the address of the old one and a page that had shown the
old picture kept showing it. The file name now carries a digest of the bytes.
"""

import io

import pytest
from fastapi import status
from PIL import Image


def _auth(user) -> dict:
    from app.services.token_service import create_access_token

    token = create_access_token(
        {'sub': str(user.id), 'org_id': str(user.organization_id), 'role': user.role}
    )
    return {'Authorization': f'Bearer {token}'}


def _png(colour: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new('RGB', (4, 4), colour).save(buffer, 'PNG')
    return buffer.getvalue()


@pytest.mark.integration
class TestAReplacedCoverIsANewAddress:
    def _upload(self, client, item, headers, colour) -> str:
        r = client.post(
            f'/api/v1/items/{item.id}/image',
            headers=headers,
            files={'image': ('c.png', _png(colour), 'image/png')},
        )
        assert r.status_code == status.HTTP_200_OK, r.text
        return r.json()['image_url']

    def test_a_different_picture_is_served_from_a_different_address(
        self, client, test_item, test_user
    ):
        headers = _auth(test_user)
        first = self._upload(client, test_item, headers, (255, 0, 0))
        second = self._upload(client, test_item, headers, (0, 0, 255))

        assert first != second
        served = client.get(second, headers=headers)
        assert served.status_code == status.HTTP_200_OK
        assert served.content == _png((0, 0, 255))
        # Nothing names the old file any more, so it does not stay behind.
        assert client.get(first, headers=headers).status_code == 404

    def test_the_same_picture_twice_keeps_one_address_and_its_file(
        self, client, test_item, test_user
    ):
        headers = _auth(test_user)
        first = self._upload(client, test_item, headers, (0, 255, 0))
        second = self._upload(client, test_item, headers, (0, 255, 0))

        assert first == second
        assert client.get(second, headers=headers).status_code == status.HTTP_200_OK

    def test_removing_the_photo_removes_the_file_the_row_names(
        self, client, test_item, test_user
    ):
        headers = _auth(test_user)
        url = self._upload(client, test_item, headers, (9, 9, 9))

        gone = client.delete(f'/api/v1/items/{test_item.id}/image', headers=headers)

        assert gone.status_code == status.HTTP_204_NO_CONTENT, gone.text
        assert client.get(url, headers=headers).status_code == 404
