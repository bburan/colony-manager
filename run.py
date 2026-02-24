from app import create_app

# Instantiate the application using the factory function
app = create_app()

if __name__ == '__main__':
    # Run the application in debug mode (turn off for production!)
    app.run(host='0.0.0.0', port=9001, debug=True)
