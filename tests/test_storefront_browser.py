import asyncio
import base64
import json
import os
from pathlib import Path
from uuid import uuid4

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from src.api import create_app
from tests.test_api import api_settings, auth_app
from tests.test_commerce_engine import ADDRESS, shop

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL")
    or os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 and provide local Postgres plus Chrome CDP on port 9223",
)


def test_browser_sign_in_cart_budget_review_confirmation_and_reconnect():
    async def run():
        async with shop() as (pool, _engines, products, users):
            extra_ids = [str(uuid4()) for _ in range(61)]
            products.extend(extra_ids)
            async with pool.connection() as connection, connection.cursor() as cursor:
                await cursor.executemany(
                    "insert into public.products (uniq_id, product_name, discounted_price) values (%s, %s, %s)",
                    [
                        (product_id, "Browsing fixture", 1000)
                        for product_id in extra_ids
                    ],
                )
                await cursor.executemany(
                    "insert into public.demo_inventory (product_id, available) values (%s, 10)",
                    [(product_id,) for product_id in extra_ids],
                )
                await cursor.execute(
                    "update public.products set product_specifications=%s, product_rating='4.5' where uniq_id=%s",
                    (
                        json.dumps(
                            {
                                "product_specification": [
                                    {"key": "Color", "value": "Blue"},
                                    {"key": "Size", "value": "M"},
                                ]
                            }
                        ),
                        products[0],
                    ),
                )
            authority = auth_app({"valid": users[0]})

            @web.middleware
            async def cors(request, handler):
                response = (
                    web.Response(status=204)
                    if request.method == "OPTIONS"
                    else await handler(request)
                )
                response.headers.update(
                    {
                        "Access-Control-Allow-Origin": request.headers.get(
                            "Origin", "*"
                        ),
                        "Access-Control-Allow-Headers": "apikey, Authorization, Content-Type",
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    }
                )
                return response

            async def login(request):
                data = await request.json()
                assert data == {
                    "email": "qa@example.test",
                    "password": "local-test-only",
                }
                return web.json_response(
                    {
                        "access_token": "valid",
                        "refresh_token": "qa-refresh",
                        "expires_in": 3600,
                        "user": {"id": str(users[0]), "email": "qa@example.test"},
                    }
                )

            authority.middlewares.append(cors)
            authority.router.add_post("/auth/v1/token", login)
            async with (
                TestServer(authority) as auth_server,
                TestServer(create_app(api_settings(auth_server), pool=pool)) as server,
                aiohttp.ClientSession() as http,
            ):
                targets = await (await http.get("http://127.0.0.1:9223/json")).json()
                target = next(item for item in targets if item.get("type") == "page")
                original_url = target["url"]
                async with http.ws_connect(target["webSocketDebuggerUrl"]) as ws:
                    request_id = 0
                    errors = []

                    async def call(method, params=None):
                        nonlocal request_id
                        request_id += 1
                        await ws.send_json(
                            {"id": request_id, "method": method, "params": params or {}}
                        )
                        while True:
                            response = await ws.receive_json()
                            if response.get("method") == "Runtime.exceptionThrown":
                                errors.append(
                                    response["params"]["exceptionDetails"]["text"]
                                )
                            if response.get("id") == request_id:
                                assert "error" not in response, response
                                return response.get("result", {})

                    async def evaluate(expression):
                        result = await call(
                            "Runtime.evaluate",
                            {
                                "expression": expression,
                                "returnByValue": True,
                                "awaitPromise": True,
                            },
                        )
                        return result.get("result", {}).get("value")

                    async def wait(expression):
                        for _ in range(120):
                            if await evaluate(f"Boolean({expression})"):
                                return
                            await asyncio.sleep(0.1)
                        raise AssertionError(
                            "Browser condition timed out: " + expression
                        )

                    async def screenshot(path):
                        result = await call(
                            "Page.captureScreenshot",
                            {"format": "png", "captureBeyondViewport": False},
                        )
                        Path(path).write_bytes(base64.b64decode(result["data"]))

                    try:
                        await call("Runtime.enable")
                        await call(
                            "Emulation.setDeviceMetricsOverride",
                            {
                                "width": 1440,
                                "height": 1000,
                                "deviceScaleFactor": 1,
                                "mobile": False,
                            },
                        )
                        await call("Page.navigate", {"url": str(server.make_url("/"))})
                        await wait(
                            "typeof ui !== 'undefined' && !!ui.config && document.querySelector('#account-button')"
                        )
                        await evaluate(
                            "document.querySelector('#account-button').click(); document.querySelector('#email-input').value='qa@example.test'; document.querySelector('#password-input').value='local-test-only'; document.querySelector('#auth-form').requestSubmit()"
                        )
                        await wait(
                            "document.querySelectorAll('.product-card').length >= 60 && !ui.busy"
                        )
                        assert await evaluate(
                            "getComputedStyle(document.querySelector('.hero')).display === 'none'"
                        )
                        assert await evaluate(
                            "getComputedStyle(document.querySelector('.announcement')).display === 'none'"
                        )
                        assert await evaluate(
                            "getComputedStyle(document.querySelector('.voice-panel')).display !== 'none'"
                        )
                        assert await evaluate(
                            "location.pathname === '/' && document.querySelector('#cart-page').hidden"
                        )
                        assert not await evaluate(
                            "document.querySelector('#pagination')"
                        )
                        await evaluate(
                            "document.querySelector('#catalog-sentinel').scrollIntoView()"
                        )
                        await wait(
                            "document.querySelectorAll('.product-card').length === 63 && !ui.catalogLoading"
                        )
                        await evaluate("scrollTo(0,0)")
                        assert await evaluate(
                            "document.querySelector('#catalog-sidebar').getBoundingClientRect().right < document.querySelector('#product-grid').getBoundingClientRect().left && document.querySelector('.catalog-filter-panel').open"
                        )
                        await screenshot("/tmp/kaufmann-catalog-page.png")
                        await evaluate(
                            "handleAgentNavigation({type:'catalog',query:'shirt',category:'',filters:{color:'Blue',size:'M'},min_rating:4,availability:'available',sort_by:'rating_desc'})"
                        )
                        await wait("!ui.catalogLoading && ui.products.length === 1")
                        assert await evaluate(
                            "document.querySelector('#filter-color').value === 'Blue' && document.querySelector('#filter-size').value === 'M' && document.querySelector('#filter-rating').value === '4' && document.querySelector('#sort-by').value === 'rating_desc'"
                        )
                        await evaluate(
                            "document.querySelector('#filter-color').value=''; document.querySelector('#filter-color').dispatchEvent(new Event('change'))"
                        )
                        await wait(
                            "!ui.busy && !ui.catalogLoading && !ui.attributeFilters.color"
                        )
                        await evaluate(
                            "document.querySelector('#clear-filters').click(); document.querySelector('#search-input').value=''"
                        )
                        await wait("!ui.busy && !ui.catalogLoading")

                        await evaluate(
                            "handleAgentNavigation({type:'catalog',query:'',category:'',min_price_paise:10000,max_price_paise:100000,sort_by:'price_asc'})"
                        )
                        await wait("!ui.catalogLoading && ui.sortBy === 'price_asc'")
                        assert await evaluate(
                            "ui.products.every(p=>p.price_paise>=10000 && p.price_paise<=100000)"
                        )
                        assert await evaluate(
                            "document.querySelector('#result-label').textContent.includes('Price: low to high')"
                        )
                        await evaluate(
                            "document.querySelector('#clear-filters').click()"
                        )
                        await wait(
                            "!ui.busy && !ui.catalogLoading && ui.minPrice === null && ui.sortBy === 'relevance'"
                        )

                        await evaluate("""window.__originalVoiceSDK = window.LivekitClient;
                            window.__voiceCheck = {microphone:false, selections:[]};
                            window.LivekitClient = {...window.LivekitClient, Room:class {
                                constructor() { window.__voiceRoom=this; this.handlers={}; this.remoteParticipants=new Map([['agent',{isAgent:true,identity:'agent'}]]); this.localParticipant={setMicrophoneEnabled:async enabled=>{window.__voiceCheck.microphone=enabled;},publishData:async payload=>{window.__voiceCheck.selections.push(JSON.parse(new TextDecoder().decode(payload)));}}; }
                                on(name,callback) { this.handlers[name]=callback; return this; }
                                async connect() {}
                                async startAudio() {}
                                async disconnect() { window.__voiceCheck.microphone=false; }
                            }};
                            document.querySelector('#voice-button').click();""")
                        await wait(
                            "document.querySelector('#voice-button').getAttribute('aria-label') === 'End voice'"
                        )
                        assert await evaluate("window.__voiceCheck.microphone")
                        await evaluate(
                            "window.__voiceRoom.handlers[LivekitClient.RoomEvent.DataReceived](new TextEncoder().encode(JSON.stringify({type:'ready'})),{isAgent:true},0,'kaufmann.navigation')"
                        )
                        await evaluate(
                            "document.querySelector('.product-name').click()"
                        )
                        await wait(
                            "location.pathname.startsWith('/product/') && !ui.busy"
                        )
                        await screenshot("/tmp/kaufmann-product-page.png")
                        assert await evaluate(
                            "document.querySelector('#product-detail').textContent.includes('Want more details?')"
                        )
                        await wait("window.__voiceCheck.selections.length === 1")
                        assert (
                            await evaluate("window.__voiceCheck.selections[0].type")
                            == "product_selected"
                        )
                        await evaluate(
                            "window.__voiceRoom.handlers[LivekitClient.RoomEvent.DataReceived](new TextEncoder().encode(JSON.stringify({type:'product',product_id:ui.products[1].id,version:ui.cart.version})),{isAgent:true},0,'kaufmann.navigation')"
                        )
                        await wait(
                            "location.pathname === '/product/' + ui.products[1].id"
                        )
                        assert (
                            await evaluate("window.__voiceCheck.selections.length") == 1
                        )
                        await evaluate(
                            "window.__voiceRoom.handlers[LivekitClient.RoomEvent.DataReceived](new TextEncoder().encode(JSON.stringify({type:'cart',version:ui.cart.version})),{isAgent:true},0,'kaufmann.navigation')"
                        )
                        await wait(
                            "location.pathname === '/cart' && !document.querySelector('#cart-page').hidden"
                        )
                        await evaluate(
                            "document.querySelector('#voice-button').click()"
                        )
                        await wait(
                            "document.querySelector('#voice-button').getAttribute('aria-pressed') === 'false'"
                        )
                        assert not await evaluate("window.__voiceCheck.microphone")
                        await evaluate(
                            "window.LivekitClient=window.__originalVoiceSDK; delete window.__originalVoiceSDK; delete window.__voiceCheck; delete window.__voiceRoom; document.querySelector('#cart-page [data-browse-products]').click()"
                        )
                        await evaluate("document.querySelector('.add-button').click()")
                        await wait(
                            "document.querySelector('#basket-count').textContent === '1' && !ui.busy"
                        )
                        await wait("location.pathname === '/cart' && !ui.busy")
                        await evaluate(
                            "document.querySelector('#cart-page [data-browse-products]').click(); document.querySelectorAll('.add-button')[1].click()"
                        )
                        await wait(
                            "location.pathname === '/cart' && ui.cart.items.length === 2 && !ui.busy"
                        )
                        assert await evaluate("ui.cart.total_paise") == 16000
                        await call("Page.reload")
                        await wait(
                            "typeof ui !== 'undefined' && ui.cart?.items.length === 2 && !ui.busy"
                        )
                        assert (
                            await evaluate(
                                "document.querySelectorAll('#cart-items .cart-item').length"
                            )
                            == 2
                        )
                        await screenshot("/tmp/kaufmann-cart-page.png")
                        await evaluate(
                            """document.querySelector('#cart-items [data-product-id="PRODUCT_ID"] .cart-item-bottom > button').click()""".replace(
                                "PRODUCT_ID", products[0]
                            )
                        )
                        await wait("ui.cart.items.length === 1 && !ui.busy")
                        await evaluate(
                            "document.querySelector('#address-details').open=true"
                        )
                        for name, value in ADDRESS.items():
                            if name != "country":
                                await evaluate(
                                    f"document.querySelector('#address-form [name={name}]').value={json.dumps(value)}"
                                )
                        await evaluate(
                            "document.querySelector('#address-form').requestSubmit()"
                        )
                        await wait(
                            "ui.cart.address?.postal_code === '500001' && !ui.busy"
                        )
                        await evaluate(
                            "document.querySelector('#budget-input').value='50'; document.querySelector('#budget-form').requestSubmit()"
                        )
                        await wait("ui.cart.budget_paise === 5000 && !ui.busy")
                        await evaluate(
                            "document.querySelector('.quantity-control button:last-child').click()"
                        )
                        await wait(
                            "document.querySelector('#budget-dialog').open && !ui.busy"
                        )
                        await evaluate(
                            "document.querySelector('#exception-approve').click()"
                        )
                        await wait(
                            "document.querySelector('#basket-count').textContent === '2' && !ui.busy"
                        )
                        assert await evaluate("ui.cart.total_paise") == 12000
                        assert await evaluate("ui.cart.budget_paise") == 5000
                        await evaluate(
                            "document.querySelector('#cart-page [data-browse-products]').click()"
                        )
                        await evaluate(
                            "[...document.querySelectorAll('.compare-check input')].slice(0,2).forEach(input => input.click()); document.querySelector('#compare-button').click()"
                        )
                        await wait(
                            "document.querySelector('#comparison-table table') && !ui.busy"
                        )
                        await evaluate(
                            "document.querySelector('#compare-dialog [data-close-dialog]').click(); document.querySelector('#basket-button').click()"
                        )
                        await wait("location.pathname === '/cart' && !ui.busy")
                        await evaluate(
                            "document.querySelector('#checkout-button').click()"
                        )
                        await wait(
                            "document.querySelector('#checkout-dialog').open && !document.querySelector('#review-confirm').disabled"
                        )
                        await evaluate(
                            "document.querySelector('#review-cancel').click()"
                        )
                        await wait(
                            "!document.querySelector('#checkout-dialog').open && !ui.cart.pending_review && !ui.busy"
                        )
                        await evaluate(
                            "document.querySelector('#checkout-button').click()"
                        )
                        await wait(
                            "document.querySelector('#checkout-dialog').open && !document.querySelector('#review-confirm').disabled"
                        )
                        await evaluate(
                            "document.querySelector('#review-confirm').click()"
                        )
                        await wait(
                            "document.querySelector('#order-dialog').open && document.querySelector('#basket-count').textContent === '0'"
                        )
                        async with pool.connection() as connection:
                            order = await (
                                await connection.execute(
                                    "select id, total_paise from public.orders where user_id = %s",
                                    (users[0],),
                                )
                            ).fetchall()
                            assert len(order) == 1
                            assert order[0]["total_paise"] == 12000
                            inventory = await (
                                await connection.execute(
                                    "select available from public.demo_inventory where product_id = %s",
                                    (products[1],),
                                )
                            ).fetchone()
                            assert inventory["available"] == 8
                        assert await evaluate("location.pathname") == "/cart"
                        await call("Page.reload")
                        await wait(
                            "typeof ui !== 'undefined' && !!ui.cart?.last_order_id && !ui.busy"
                        )
                        assert (
                            await evaluate(
                                "document.querySelector('#basket-count').textContent"
                            )
                            == "0"
                        )
                        await evaluate(
                            "document.querySelector('#orders-button').click()"
                        )
                        await wait(
                            "location.pathname === '/orders' && document.querySelectorAll('.order-history-card').length === 1 && !ui.busy"
                        )
                        assert "120" in await evaluate(
                            "document.querySelector('#orders-list').textContent"
                        )
                        await call("Page.reload")
                        await wait(
                            "location.pathname === '/orders' && document.querySelectorAll('.order-history-card').length === 1 && !ui.busy"
                        )
                        await evaluate(
                            "document.querySelector('#last-order-button').click()"
                        )
                        await wait("document.querySelector('#order-dialog').open")
                        assert str(order[0]["id"]) in await evaluate(
                            "document.querySelector('#order-content').textContent"
                        )
                        await evaluate(
                            "document.querySelector('#order-dialog [data-close-dialog]').click()"
                        )
                        await evaluate(
                            "document.querySelector('#profile-button').click()"
                        )
                        await wait(
                            "location.pathname === '/profile' && !!ui.profile && !ui.busy"
                        )
                        await evaluate(
                            "document.querySelector('#profile-form [name=name]').value='QA Shopper'; document.querySelector('#profile-form [name=phone]').value='+91 9876543210'; document.querySelector('#profile-form').requestSubmit()"
                        )
                        await wait("!ui.busy && ui.profile.name === 'QA Shopper'")
                        await evaluate(
                            "document.querySelector('#profile-current-address button').click()"
                        )
                        await wait(
                            "document.querySelector('#profile-address-dialog').open"
                        )
                        await evaluate(
                            "document.querySelector('#profile-address-form').requestSubmit()"
                        )
                        await wait(
                            "!ui.busy && ui.profile.addresses.length === 1 && !document.querySelector('#profile-address-dialog').open"
                        )
                        await evaluate(
                            "document.querySelector('.saved-address .text-button').click(); document.querySelector('#profile-address-form [name=state]').value='Karnataka'; document.querySelector('#profile-address-form').requestSubmit()"
                        )
                        await wait(
                            "!ui.busy && ui.profile.addresses[0].address.state === 'Karnataka'"
                        )
                        assert await evaluate(
                            "ui.profile.addresses[0].address.city === 'Hyderabad'"
                        )
                        await call("Page.reload")
                        await wait(
                            "location.pathname === '/profile' && ui.profile?.name === 'QA Shopper' && !ui.busy"
                        )
                        await screenshot("/tmp/kaufmann-profile-page.png")
                        await call(
                            "Emulation.setDeviceMetricsOverride",
                            {
                                "width": 390,
                                "height": 844,
                                "deviceScaleFactor": 1,
                                "mobile": True,
                            },
                        )
                        await evaluate(
                            "navigate('/'); document.querySelector('#open-catalog-filters').click()"
                        )
                        await wait(
                            "document.querySelector('#catalog-filter-drawer').open"
                        )
                        assert await evaluate(
                            "document.querySelector('#filter-drawer-content .catalog-filter-panel').open && getComputedStyle(document.querySelector('#catalog-sidebar')).display === 'none'"
                        )
                        await screenshot("/tmp/kaufmann-mobile-filters.png")
                        await evaluate(
                            "document.querySelector('#apply-catalog-filters').click()"
                        )
                        assert await evaluate(
                            "!document.querySelector('#catalog-filter-drawer').open"
                        )
                        assert not await evaluate(
                            "document.documentElement.scrollWidth > innerWidth"
                        )
                        screenshot = await call(
                            "Page.captureScreenshot",
                            {"format": "png", "captureBeyondViewport": True},
                        )
                        Path("/tmp/kaufmann-storefront-authenticated.png").write_bytes(
                            base64.b64decode(screenshot["data"])
                        )
                        assert errors == []
                    finally:
                        await call("Emulation.clearDeviceMetricsOverride")
                        await call("Page.navigate", {"url": original_url})

    asyncio.run(run())
