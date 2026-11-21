typedef unsigned char Byte;
typedef Byte Octet;
typedef struct
{
    Octet data[8];
    unsigned int length;
} Buffer;

Octet buffer_checksum(const Buffer *buffer);

int main(void)
{
    Buffer buffer = {{1, 2, 3, 4, 5, 6, 7, 8}, 8};
    Octet checksum;

    checksum = buffer_checksum(&buffer);

    return 0;
}

// Return the checksum of the bytes stored in the buffer.
Octet buffer_checksum(const Buffer *buffer)
{
