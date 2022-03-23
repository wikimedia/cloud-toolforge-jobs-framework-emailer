# Jobs Framework API

This is the source code of the Toolforge Jobs Framework emailer.

The TJF creates an abstraction layer over kubernetes Jobs, CronJobs and Deployments to allow
operating a Kubernetes installation as if it were a Grid (like GridEngine).

This component emails users when events about their jobs happen.

This was created for [Wikimedia Toolforge](https://tolforge.org).

## Installation

Per https://phabricator.wikimedia.org/T303931, use `deploy.sh`.

For additional instructions, see `deployment/README.md`.

## Development

See `devel/README.md`.

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Please make sure to update tests as appropriate.

## License
[AGPLv3](https://choosealicense.com/licenses/agpl-3.0/)
