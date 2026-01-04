"""Architecture validation - check for import conflicts, circular dependencies, type issues"""
import sys
import importlib
import traceback
from pathlib import Path


def test_imports():
    """Test that all modules can be imported without errors"""
    modules_to_test = [
        'saferun.app.services.github',
        'saferun.app.routers.github_webhooks',
        'saferun.app.notify',
        'saferun.app.db',
        'saferun.app.main',
    ]
    
    errors = []
    
    for module_name in modules_to_test:
        try:
            importlib.import_module(module_name)
            print(f"✅ {module_name} imported successfully")
        except Exception as e:
            errors.append({
                'module': module_name,
                'error': str(e),
                'traceback': traceback.format_exc()
            })
            print(f"❌ {module_name} import failed: {e}")
    
    return errors


def test_circular_dependencies():
    """Check for circular dependency issues"""
    print("\n🔍 Checking for circular dependencies...")
    
    # Test import order
    test_orders = [
        ['saferun.app.db', 'saferun.app.models.action', 'saferun.app.routers.github_webhooks'],
        ['saferun.app.services.github', 'saferun.app.routers.github_webhooks'],
        ['saferun.app.notify', 'saferun.app.routers.github_webhooks'],
    ]
    
    errors = []
    
    for order in test_orders:
        # Clear imported modules
        for mod in list(sys.modules.keys()):
            if mod.startswith('saferun'):
                del sys.modules[mod]
        
        try:
            for module_name in order:
                importlib.import_module(module_name)
            print(f"✅ Import order OK: {' → '.join(order)}")
        except Exception as e:
            errors.append({
                'order': order,
                'error': str(e)
            })
            print(f"❌ Import order failed: {' → '.join(order)}")
            print(f"   Error: {e}")
    
    return errors


def test_missing_dependencies():
    """Check for missing external dependencies"""
    print("\n📦 Checking external dependencies...")
    
    required_packages = [
        'fastapi',
        'httpx',
        'sqlalchemy',
        'pytest',
    ]
    
    missing = []
    
    for package in required_packages:
        try:
            importlib.import_module(package)
            print(f"✅ {package} available")
        except ImportError:
            missing.append(package)
            print(f"❌ {package} missing")
    
    return missing


def test_function_signatures():
    """Validate function signatures match expected interfaces"""
    print("\n🔧 Checking function signatures...")
    
    from saferun.app.services import github
    from saferun.app import notify
    import inspect
    
    checks = []
    
    # Check verify_webhook_signature
    sig = inspect.signature(github.verify_webhook_signature)
    params = list(sig.parameters.keys())
    if params != ['payload', 'signature']:
        checks.append(f"❌ verify_webhook_signature params: expected ['payload', 'signature'], got {params}")
    else:
        print("✅ verify_webhook_signature signature OK")
    
    # Check calculate_github_risk_score
    sig = inspect.signature(github.calculate_github_risk_score)
    params = list(sig.parameters.keys())
    if params != ['event_type', 'payload']:
        checks.append(f"❌ calculate_github_risk_score params: expected ['event_type', 'payload'], got {params}")
    else:
        print("✅ calculate_github_risk_score signature OK")
    
    # REMOVED: format_slack_message was deleted as part of Cloud-First security migration
    # All Slack notifications now use OAuth tokens via notifier.publish()
    # Check notifier instance exists
    if hasattr(notify, 'notifier'):
        print("✅ notifier instance available (OAuth-based Slack)")
    else:
        checks.append("❌ notifier instance not found in notify module")
    
    return checks


def test_database_schema():
    """Validate database schema compatibility"""
    print("\n🗄️  Checking database schema...")
    
    try:
        from saferun.app import db
        
        # Test that init_db runs without errors
        # We won't actually run it, just check it's callable
        assert callable(db.init_db)
        print("✅ db.init_db is callable")
        
        # Check key functions exist
        required_functions = ['fetchall', 'fetchone', 'exec', 'upsert_change']
        for func_name in required_functions:
            if not hasattr(db, func_name):
                return [f"❌ Missing db function: {func_name}"]
            print(f"✅ db.{func_name} exists")
        
        return []
        
    except Exception as e:
        return [f"❌ Database schema error: {e}"]


def test_router_registration():
    """Check that routers are properly registered"""
    print("\n🛣️  Checking router registration...")
    
    try:
        from saferun.app.main import app
        
        # Get all registered routes
        routes = [route.path for route in app.routes]
        
        required_routes = [
            '/webhooks/github/install',
            '/webhooks/github/event',
            '/webhooks/github/revert/{action_id}',
        ]
        
        missing = []
        for route in required_routes:
            if route not in routes:
                missing.append(route)
                print(f"❌ Missing route: {route}")
            else:
                print(f"✅ Route registered: {route}")
        
        return missing
        
    except Exception as e:
        return [f"❌ Router registration error: {e}"]


def main():
    """Run all architecture checks"""
    print("=" * 60)
    print("🏗️  ARCHITECTURE VALIDATION")
    print("=" * 60)
    
    all_errors = []
    
    # Test imports
    print("\n1️⃣  Testing module imports...")
    import_errors = test_imports()
    if import_errors:
        all_errors.extend(import_errors)
    
    # Test circular dependencies
    print("\n2️⃣  Testing circular dependencies...")
    circular_errors = test_circular_dependencies()
    if circular_errors:
        all_errors.extend(circular_errors)
    
    # Test missing dependencies
    print("\n3️⃣  Testing external dependencies...")
    missing_deps = test_missing_dependencies()
    if missing_deps:
        all_errors.append({'type': 'missing_packages', 'packages': missing_deps})
    
    # Test function signatures
    print("\n4️⃣  Testing function signatures...")
    sig_errors = test_function_signatures()
    if sig_errors:
        all_errors.extend(sig_errors)
    
    # Test database schema
    print("\n5️⃣  Testing database schema...")
    db_errors = test_database_schema()
    if db_errors:
        all_errors.extend(db_errors)
    
    # Test router registration
    print("\n6️⃣  Testing router registration...")
    router_errors = test_router_registration()
    if router_errors:
        all_errors.append({'type': 'missing_routes', 'routes': router_errors})
    
    # Summary
    print("\n" + "=" * 60)
    if not all_errors:
        print("✅ ALL CHECKS PASSED! Architecture is valid.")
        return 0
    else:
        print(f"❌ FOUND {len(all_errors)} ISSUE(S):")
        for i, error in enumerate(all_errors, 1):
            print(f"\n{i}. {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
