# Docker Compose Setup Guide

This guide explains how to deploy and run the application using Docker Compose.

## Prerequisites

- Docker Desktop installed on your system
- Git (to clone the repository) - Download from https://git-scm.com/
- Valid OpenAI API key

**Alternative**: If you don't want to install Git, you can download the repository as a ZIP file from GitHub.

## Quick Start

### 1. Clone the Repository

```bash
git clone -b docker-deploy https://github.com/zhanliuch/aid-gem.git
cd aid-gem
```

### 2. Create Environment File

Create a `.env` file in the project root directory with the following content:

```bash
FLASK_DEBUG=0
OPENAI_API_KEY=your-openai-api-key-here
FLASK_SECRET_KEY=your-secret-key-here
```

**Important**: Replace `your-openai-api-key-here` with your actual OpenAI API key.

### 3. Build and Run

```bash
# Build the Docker image
docker-compose build

# Start the application
docker-compose up -d
```

### 4. Access the Application

Open your browser and navigate to: `http://localhost:5000`

## Configuration

### Environment Variables

The application uses the following environment variables in the `.env` file:

| Variable | Description | Required |
|----------|-------------|----------|
| `FLASK_DEBUG` | Set to `0` for production | Yes |
| `OPENAI_API_KEY` | Your OpenAI API key | Yes |
| `FLASK_SECRET_KEY` | Secret key for Flask sessions | Yes |

### Docker Compose Configuration

The `docker-compose.yml` file includes:

- **Port mapping**: `5000:5000` (host:container)
- **Volume mounts**: 
  - `./uploads:/app/uploads` - File uploads
  - `./outputs:/app/outputs` - Processing results
  - `./logs:/app/logs` - Application logs
- **DNS configuration**: Uses Google DNS (8.8.8.8, 8.8.4.4)
- **Timezone**: Set to `Europe/Zurich` (Switzerland)

## Usage Commands

### Start the Application

```bash
# Start in background
docker-compose up -d

# Start with logs visible
docker-compose up
```

### Stop the Application

```bash
# Stop containers (keeps containers for quick restart)
docker-compose stop

# Stop and remove containers
docker-compose down
```

### Restart the Application

```bash
# After stopping with 'stop'
docker-compose start

# After stopping with 'down'
docker-compose up -d
```

### View Logs

```bash
# View current logs
docker-compose logs

# Follow logs in real-time
docker-compose logs -f
```

### Check Status

```bash
# Check running containers
docker-compose ps

# Check application health
curl http://localhost:5000/test
```

## Development vs Production

### Development Mode

For development, you can enable debug mode:

```bash
# In .env file
FLASK_DEBUG=1
```

### Production Mode

For production deployment:

```bash
# In .env file
FLASK_DEBUG=0
```

## Troubleshooting

### Common Issues

1. **Port 5000 already in use**
   ```bash
   # Change port in docker-compose.yml
   ports:
     - "5001:5000"  # Use port 5001 instead
   ```

2. **DNS resolution issues**
   ```bash
   # The configuration already includes Google DNS
   dns:
     - 8.8.8.8
     - 8.8.4.4
   ```

3. **Permission issues with volumes**
   ```bash
   # Create directories with proper permissions
   mkdir -p uploads outputs logs
   chmod 755 uploads outputs logs
   ```

4. **Container won't start**
   ```bash
   # Check logs for errors
   docker-compose logs
   
   # Rebuild without cache
   docker-compose build --no-cache
   ```

### Debugging Commands

```bash
# Execute commands inside the container
docker-compose exec web bash

# Check container timezone
docker-compose exec web date

# Check DNS resolution
docker-compose exec web nslookup google.com

# Check Python dependencies
docker-compose exec web pip list
```

## File Structure

```
project-folder/
├── docker-compose.yml          # Docker Compose configuration
├── Dockerfile                  # Docker image build instructions
├── requirements.txt           # Python dependencies
├── app.py                     # Main Flask application
├── .env                       # Environment variables (create this)
├── uploads/                   # Upload directory (auto-created)
├── outputs/                   # Output directory (auto-created)
├── logs/                      # Log directory (auto-created)
├── templates/                 # HTML templates
├── config/                    # Configuration files
└── README_docker-compose.md   # This file
```

## Backup and Maintenance

### Backup Important Data

```bash
# Backup uploads and outputs
tar -czf backup-$(date +%Y%m%d).tar.gz uploads/ outputs/ logs/
```

### Clean Up Docker

```bash
# Remove unused images
docker image prune

# Remove all unused Docker resources
docker system prune -a
```

### Update the Application

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## Security Notes

- Never commit the `.env` file to version control
- Use strong secret keys in production
- Regularly update your OpenAI API key
- Monitor logs for suspicious activity

## Support

For issues related to:
- **Docker setup**: Check Docker Desktop status and logs
- **Application errors**: Check `logs/app.log` or `docker-compose logs`
- **Network issues**: Verify DNS and firewall settings
- **API issues**: Verify OpenAI API key and quota

## Performance Tips

- The application uses single worker with 4 threads for optimal performance
- Processing time: ~1 minute per article
- Maximum recommended: 30 articles per batch
- Container timeout: Unlimited (suitable for long-running processes)