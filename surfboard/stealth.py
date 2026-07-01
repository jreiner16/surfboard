"""Playwright stealth init script — prevents bot detection by faking browser fingerprint."""

STEALTH_INIT_SCRIPT = """
// Remove webdriver property
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Chrome plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// Chrome runtime
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {},
};

// Permissions
navigator.permissions.query = (() => {
    const original = navigator.permissions.query.bind(navigator.permissions);
    return (params) => {
        if (params.name === 'notifications') {
            return Promise.resolve({ state: 'denied', onchange: null });
        }
        return original(params);
    };
})();

// WebGL vendor
const getExt = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function(type, ...args) {
    const ctx = getExt.call(this, type, ...args);
    if (ctx && type === 'webgl') {
        const getParam = ctx.getParameter;
        ctx.getParameter = function(param) {
            if (param === 37445) return 'Intel Inc.';
            if (param === 37446) return 'Intel Iris OpenGL Engine';
            return getParam.call(this, param);
        };
    }
    return ctx;
};

// Remove headless chrome detection
Object.defineProperty(navigator, 'connection', {
    get: () => ({ rtt: 100, effectiveType: '4g' }),
});

// Fake device memory
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8,
});

// Fake hardware concurrency
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8,
});
"""
