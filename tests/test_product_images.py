import json

from src.catalog.products import product_images


def test_legacy_images_are_normalized_and_deduplicated():
    assert product_images(
        json.dumps(
            [
                "http://img6a.flixcart.com/image/example.jpeg",
                "http://img5a.flixcart.com/image/example.jpeg",
                "https://example.com/product.jpg",
                "javascript:alert(1)",
                "https://user:password@example.com/private.jpg",
            ]
        )
    ) == [
        "https://rukminim2.flixcart.com/image/example.jpeg",
        "https://example.com/product.jpg",
    ]


def test_unknown_image_hosts_are_preserved():
    assert product_images('["https://images.example.com/item.png"]') == [
        "https://images.example.com/item.png"
    ]
