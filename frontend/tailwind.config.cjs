/** @type {import('tailwindcss').Config} */
module.exports = {
    darkMode: 'media',
    content: ["./src/**/*.{html,js,ts,tsx}"],
    theme: {
        extend: {
            colors: {
                brand: {
                    purple: '#7400f6',
                    navy: '#190075',
                    'light-purple': '#9d30a0',
                    teal: '#048fb5',
                    green: '#2CDFB5',
                    red: '#FC7091',
                    amber: '#FEC200',
                },
            },
            fontFamily: {
                sans: ['Inter', 'system-ui', 'sans-serif'],
                mono: ['Poppins', 'sans-serif'],
            },
        },
    },
    plugins: [],
};
