STACK_NAME=canoe-helpdesk
S3_BUCKET=my-bucket #obtain it from internal docs

gmake build SERVICE=canoe
aws --region eu-west-2 cloudformation package \
    --template-file template.yaml     \
    --output-template-file packaged.yaml     \
    --s3-bucket $S3_BUCKET
aws --region eu-west-2 cloudformation deploy \
    --template-file $PWD/packaged.yaml \
    --stack-name $STACK_NAME \
    --parameter-overrides "file://$PWD/env.json" \
    --capabilities CAPABILITY_IAM
