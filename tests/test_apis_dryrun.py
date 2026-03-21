#!/usr/bin/env python3
"""
SpreadScope - Dry-run API tests using urllib (no dependencies needed)
Tests that all public APIs respond correctly and validates response parsing.
"""

import json
import urllib.request
import urllib.error
import sys
import time

RESULTS = {}

def test_api(name, url, method='GET', data=None, headers=None):
    """Test an API endpoint and return parsed response."""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"  URL: {url}")
    print(f"  Method: {method}")
    
    try:
        if headers is None:
            headers = {'Content-Type': 'application/json'}
        
        if data and isinstance(data, dict):
            data = json.dumps(data).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        
        start = time.time()
        with urllib.request.urlopen(req, timeout=15) as response:
            elapsed = time.time() - start
            body = response.read().decode('utf-8')
            parsed = json.loads(body)
            
            print(f"  Status: {response.status}")
            print(f"  Time: {elapsed:.2f}s")
            print(f"  Response size: {len(body)} bytes")
            
            RESULTS[name] = '✅ Success'
            return parsed
    
    except urllib.error.HTTPError as e:
        print(f"  ❌ HTTP Error: {e.code} {e.reason}")
        try:
            body = e.read().decode('utf-8')
            print(f"  Body: {body[:200]}")
        except:
            pass
        RESULTS[name] = f'❌ HTTP {e.code}'
        return None
    except urllib.error.URLError as e:
        print(f"  ❌ URL Error: {e.reason}")
        RESULTS[name] = f'❌ {e.reason}'
        return None
    except json.JSONDecodeError as e:
        print(f"  ❌ JSON parse error: {e}")
        RESULTS[name] = '❌ Invalid JSON'
        return None
    except Exception as e:
        print(f"  ❌ Error: {e}")
        RESULTS[name] = f'❌ {e}'
        return None

def main():
    print("SpreadScope - API Dry-Run Tests")
    print("Testing all public endpoints...\n")
    
    # === Test 1: Coinbase Spot ===
    data = test_api(
        'Coinbase Spot (BTC)',
        'https://api.coinbase.com/v2/prices/BTC-USD/spot'
    )
    if data and 'data' in data:
        price = float(data['data']['amount'])
        print(f"  📊 BTC Price: ${price:,.2f}")
        RESULTS['Coinbase Spot (BTC)'] = f'✅ BTC = ${price:,.2f}'
    
    data = test_api(
        'Coinbase Spot (ETH)',
        'https://api.coinbase.com/v2/prices/ETH-USD/spot'
    )
    if data and 'data' in data:
        price = float(data['data']['amount'])
        print(f"  📊 ETH Price: ${price:,.2f}")
        RESULTS['Coinbase Spot (ETH)'] = f'✅ ETH = ${price:,.2f}'
    
    # === Test 2: Hyperliquid allMids ===
    data = test_api(
        'Hyperliquid allMids',
        'https://api.hyperliquid.xyz/info',
        method='POST',
        data={"type": "allMids"}
    )
    if data and isinstance(data, dict):
        btc = data.get('BTC', 'N/A')
        eth = data.get('ETH', 'N/A')
        count = len(data)
        print(f"  📊 Assets: {count}")
        print(f"  📊 BTC: ${float(btc):,.2f}" if btc != 'N/A' else "  BTC: N/A")
        print(f"  📊 ETH: ${float(eth):,.2f}" if eth != 'N/A' else "  ETH: N/A")
        RESULTS['Hyperliquid allMids'] = f'✅ {count} assets, BTC=${btc}'
    
    # === Test 3: Hyperliquid metaAndAssetCtxs ===
    data = test_api(
        'Hyperliquid metaAndAssetCtxs',
        'https://api.hyperliquid.xyz/info',
        method='POST',
        data={"type": "metaAndAssetCtxs"}
    )
    if data and isinstance(data, list) and len(data) >= 2:
        universe = data[0]
        contexts = data[1]
        
        # Find BTC
        asset_names = []
        if isinstance(universe, dict) and 'universe' in universe:
            asset_names = [a.get('name', '') for a in universe['universe']]
        elif isinstance(universe, list):
            asset_names = [a.get('name', '') for a in universe]
        
        asset_count = len(contexts)
        print(f"  📊 Assets with context: {asset_count}")
        
        # Show first context as sample
        if contexts and len(contexts) > 0:
            sample = contexts[0]
            print(f"  Sample context keys: {list(sample.keys())[:8]}")
            
            # Look for funding rate
            if 'funding' in sample:
                print(f"  Sample funding rate: {sample['funding']}")
        
        RESULTS['Hyperliquid metaAndAssetCtxs'] = f'✅ {asset_count} asset contexts'
    
    # === Test 4: dYdX v4 perpetualMarkets ===
    data = test_api(
        'dYdX v4 perpetualMarkets',
        'https://indexer.dydx.trade/v4/perpetualMarkets'
    )
    if data and 'markets' in data:
        markets = data['markets']
        market_count = len(markets)
        print(f"  📊 Markets: {market_count}")
        
        # Show BTC and ETH
        for ticker in ['BTC-USD', 'ETH-USD']:
            if ticker in markets:
                m = markets[ticker]
                oracle = m.get('oraclePrice', 'N/A')
                funding = m.get('nextFundingRate', 'N/A')
                oi = m.get('openInterest', 'N/A')
                print(f"  📊 {ticker}: oracle=${oracle}, funding={funding}, OI={oi}")
        
        RESULTS['dYdX v4 perpetualMarkets'] = f'✅ {market_count} markets'
    
    # === Test 5: Pyth Network (Synthetix oracle) ===
    btc_feed = '0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43'
    data = test_api(
        'Pyth/Synthetix Oracle (BTC)',
        f'https://hermes.pyth.network/v2/updates/price/latest?ids%5B%5D={btc_feed}'
    )
    if data and 'parsed' in data and len(data['parsed']) > 0:
        entry = data['parsed'][0]
        price_data = entry.get('price', {})
        raw_price = int(price_data.get('price', 0))
        expo = int(price_data.get('expo', 0))
        price = raw_price * (10 ** expo)
        print(f"  📊 BTC Oracle Price: ${price:,.2f}")
        RESULTS['Pyth/Synthetix Oracle (BTC)'] = f'✅ BTC oracle = ${price:,.2f}'
    
    # === Test 6: Coinbase Perps (BTC-PERP-INTX) ===
    data = test_api(
        'Coinbase Perps (BTC-PERP-INTX)',
        'https://api.coinbase.com/api/v3/brokerage/products/BTC-PERP-INTX'
    )
    if data and data.get('price'):
        price = float(data['price'])
        print(f"  📊 BTC-PERP: ${price:,.2f}")
        RESULTS['Coinbase Perps (BTC-PERP-INTX)'] = f'✅ BTC-PERP = ${price:,.2f}'
    elif data:
        print(f"  Response keys: {list(data.keys())[:10]}")
        # Try to find price in nested structure
        if 'product' in data:
            product = data['product']
            price = product.get('price', 'N/A')
            print(f"  Found nested price: {price}")
    
    # === Summary ===
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    for name, result in RESULTS.items():
        print(f"  {name}: {result}")
    
    print("\n" + "=" * 60)
    success = sum(1 for r in RESULTS.values() if r.startswith('✅'))
    total = len(RESULTS)
    print(f"  {success}/{total} tests passed")
    print("=" * 60)
    
    return 0 if success >= 4 else 1  # At least 4 of 6+ should pass

if __name__ == '__main__':
    sys.exit(main())