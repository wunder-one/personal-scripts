#!/bin/bash
# create-stack - Create Docker stack directories with proper permissions
#
# This script creates properly configured directories under /opt/stacks
# for Docker Compose services with standardized permissions.
# create-stack - Create Docker stack directories with proper permissions
#Save this as /usr/local/bin/create-stack and make it executable with chmod +x /usr/local/bin/create-stack

# Function to display help information
show_help() {
  echo "Usage: create-stack <stack-name> [options]"
  echo "       create-stack --fix-all"
  echo
  echo "Creates a new Docker stack directory at /opt/stacks/<stack-name>"
  echo "with proper ownership and permissions, or fixes permissions on existing directories."
  echo
  echo "Options:"
  echo "  -h, --help     Show this help message"
  echo "  -p, --perms    Show information about the permissions being set"
  echo "  -f, --fix-all  Fix permissions on all directories under /opt/stacks"
  echo
  echo "Examples:"
  echo "  create-stack nextcloud       # Create /opt/stacks/nextcloud"
  echo "  create-stack --help          # Show this help message"
  echo "  create-stack plex --perms    # Create directory and explain permissions"
  echo "  create-stack --fix-all       # Fix permissions for all stack directories"
}

# Function to show information about permissions
show_perms_info() {
  echo "Setting up directory with these permissions:"
  echo "  - Owner: root"
  echo "  - Group: docker"
  echo "  - Permissions: 775 (rwxrwxr-x)"
  echo "  - SGID bit: enabled (new files inherit the docker group)"
  echo
  echo "This allows:"
  echo "  - Members of docker group to edit files"
  echo "  - Root ownership for security"
  echo "  - Read access for all users (good for service operation)"
}

# Function to create an empty docker-compose file
create_compose_file() {
  echo "Checking for existing docker-compose file..."
  if [ -f "/opt/stacks/$STACK_NAME/docker-compose.yml" ] || [ -f "/opt/stacks/$STACK_NAME/docker-compose.yaml" ]; then
    echo "Docker-compose file already exists in /opt/stacks/$STACK_NAME"
    echo "This script will not overwrite existing files."
    return
  fi
  if [ -d "/opt/stacks/$STACK_NAME" ] && [ ! -f "/opt/stacks/$STACK_NAME/docker-compose.yml" ] && [ ! -f "/opt/stacks/$STACK_NAME/docker-compose.yaml" ]; then
    echo "Creating empty docker-compose.yml file..."
    sudo touch "/opt/stacks/$STACK_NAME/docker-compose.yml"
    sudo chown root:docker "/opt/stacks/$STACK_NAME/docker-compose.yml"
    sudo chmod 664 "/opt/stacks/$STACK_NAME/docker-compose.yml"
  elif [ ! -d "/opt/stacks/$STACK_NAME" ]; then
    echo "Error: Directory /opt/stacks/$STACK_NAME does not exist."
    echo "Exiting script..."
    exit 1
  fi
}

# Function to set the correct permissions on a directory
set_permissions() {
  local dir="$1"
  sudo chown root:docker "$dir"
  sudo chmod 775 "$dir"
  sudo chmod g+s "$dir"
  echo "Set permissions on: $dir"
}

# Function to fix permissions on all directories
fix_all_permissions() {
  if [ ! -d "/opt/stacks" ]; then
    echo "Error: /opt/stacks directory does not exist."
    echo "Creating it now..."
    sudo mkdir -p /opt/stacks
    set_permissions "/opt/stacks"
    echo "No stack directories found."
    exit 0
  fi
  
  # Count directories to fix
  local dirs=($(find /opt/stacks -maxdepth 1 -type d | tail -n +2))
  local count=${#dirs[@]}
  
  if [ $count -eq 0 ]; then
    echo "Fixed permissions on /opt/stacks (parent directory)"
    set_permissions "/opt/stacks"
    echo "No stack subdirectories found."
    exit 0
  fi
  
  echo "Found $count stack directories to process."
  echo "This will reset permissions on all directories under /opt/stacks."
  echo "The script will set root:docker ownership and 775 permissions with SGID bit."
  read -p "Do you want to continue? (y/n): " CONFIRM
  
  case $CONFIRM in
    [Yy]*)
      echo "Fixing permissions on /opt/stacks (parent directory)"
      set_permissions "/opt/stacks"
      
      echo "Fixing permissions on all stack directories..."
      for dir in "${dirs[@]}"; do
        set_permissions "$dir"
      done
      echo "All done! Fixed permissions on $count directories."
      ;;
    *)
      echo "Operation cancelled."
      exit 0
      ;;
  esac
}

# Handle --fix-all option
if [ "$1" = "--fix-all" ] || [ "$1" = "-f" ]; then
  fix_all_permissions
  exit 0
fi

# Process help arguments
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
  show_help
  exit 0
fi

# Check if stack name is provided
if [ -z "$1" ]; then
  echo "Error: Missing stack name"
  echo "Try 'create-stack --help' for more information."
  exit 1
fi

# Get the stack name from the first argument
STACK_NAME="$1"

# Check if we should show permissions info
if [ "$2" = "--perms" ] || [ "$2" = "-p" ]; then
  show_perms_info
fi

# Check if directory already exists
if [ -d "/opt/stacks/$STACK_NAME" ]; then
  echo "Warning: Directory /opt/stacks/$STACK_NAME already exists."
  echo "This script will reset directory permissions and ownership, but won't delete any files."
  read -p "Do you want to continue? (y/n): " CONFIRM
  
  case $CONFIRM in
    [Yy]*)
      echo "Proceeding with permission reset..."
      ;;
    *)
      echo "Operation cancelled."
      exit 0
      ;;
  esac
else
  echo "Creating stack directory: /opt/stacks/$STACK_NAME"
  sudo mkdir -p "/opt/stacks/$STACK_NAME"
fi

create_compose_file

# Set or reset permissions
set_permissions "/opt/stacks/$STACK_NAME"

echo "Directory setup completed successfully!"
echo "You can now place your docker-compose.yml in /opt/stacks/$STACK_NAME/"