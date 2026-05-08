import os

from colony_manager_gui import create_app

# Instantiate the application using the factory function
app = create_app()

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes')
    app.run(host='0.0.0.0', port=5000, debug=debug)
