typedef enum
{
    STATUS_OK,
    STATUS_LOW,
    STATUS_HIGH
} Status;

typedef Status Measurement;
typedef unsigned short Limit;

Status classify_measurement(Limit value, Limit limit);

int main(void)
{
    Measurement result;

    result = classify_measurement(120, 100);

    return 0;
}

// Return STATUS_LOW, STATUS_OK, or STATUS_HIGH relative to the limit.
Status classify_measurement(Limit value, Limit limit)
{
